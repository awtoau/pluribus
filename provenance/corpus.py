"""Corpus = acceptance test; done = every required member at headline 100 % with wrong = 0.

Headline per category = matched / (matched + missing + extra + wrong) (scoring-faults rules:
missing and extra are faults equal to wrong). A member passes iff every category is 100 % and
wrong == 0. On met: open unknowns / expectations of the family -> parked (kept, queryable).
On a later failure: the failing cone's claims -> suspect, its parked items -> open, audits queued.
"""
from sqlalchemy import and_, insert, select, update

import db
import schema as S
from provenance import feedback, queries, tiers

FAULTS = ("missing", "extra", "wrong")


def headline(c):
    t = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
    return 100.0 * c["matched"] / t if t else 100.0


def member_passes(counts):
    return all(headline(c) == 100.0 and c["wrong"] == 0 for c in counts)


def ensure_member(conn, family, name, kind, commit, device=None, build_id=None, source_ref=None,
                  sha256=None, gate_script=None, required=True, expected=None):
    tiers.check(kind, tiers.CORPUS_KINDS, "corpus kind")
    r = conn.execute(select(S.corpus_members.c.id).where(and_(
        S.corpus_members.c.family == family, S.corpus_members.c.name == name))).fetchone()
    if r:
        return r[0]
    return conn.execute(insert(S.corpus_members).values(
        family=family, name=name, kind=kind, device=device, build_id=build_id, source_ref=source_ref,
        sha256=sha256, gate_script=gate_script, required=required,
        expected=expected or {"headline": 100, "wrong": 0}, added_commit=commit)).inserted_primary_key[0]


def ensure_criterion(conn, family):
    r = conn.execute(select(S.done_criteria.c.id).where(S.done_criteria.c.family == family)).fetchone()
    if r:
        return r[0]
    n = conn.execute(select(S.corpus_members.c.id).where(and_(
        S.corpus_members.c.family == family, S.corpus_members.c.required == True))).fetchall()  # noqa: E712
    return conn.execute(insert(S.done_criteria).values(
        family=family, criterion={"headline": 100, "wrong": 0, "required_members": len(n),
                                  "rule": "every required member: every category headline 100 %, wrong 0"},
        state="open", updated_at=feedback.now())).inserted_primary_key[0]


def record_gate_run(conn, family, script, commit, results, code_stamp=None, params=None, summary=None):
    """results: {member_name: {category: {matched, missing, extra, wrong, failing_claims?}}}.
    Writes gate_runs + gate_results, evaluates the done criterion, parks or reopens. Returns run id."""
    members = {r.name: r for r in conn.execute(select(S.corpus_members).where(S.corpus_members.c.family == family))}
    for name in results:
        if name not in members:
            db.die(f"gate result for {name!r} but it is not a corpus member of {family}")
    run_id = conn.execute(insert(S.gate_runs).values(
        family=family, script=script, commit=commit, code_stamp=code_stamp, params=params,
        ts=feedback.now(), passed=None, summary=summary)).inserted_primary_key[0]
    member_pass = {}
    for name, cats in results.items():
        counts = []
        for cat, c in cats.items():
            c = {k: int(c.get(k, 0)) for k in ("matched",) + FAULTS} | {"failing_claims": c.get("failing_claims")}
            h = headline(c)
            ok = h == 100.0 and c["wrong"] == 0
            conn.execute(insert(S.gate_results).values(
                run_id=run_id, member_id=members[name].id, category=cat, matched=c["matched"],
                missing=c["missing"], extra=c["extra"], wrong=c["wrong"], headline=h, passed=ok,
                failing_claims=c["failing_claims"]))
            counts.append(c)
        member_pass[name] = member_passes(counts)
    required = [m for m in members.values() if m.required]
    all_pass = bool(required) and all(member_pass.get(m.name, False) for m in required)
    conn.execute(update(S.gate_runs).where(S.gate_runs.c.id == run_id).values(passed=all_pass))
    ensure_criterion(conn, family)
    if all_pass:
        _mark_met(conn, family, run_id, commit)
    else:
        failing = [n for n, ok in member_pass.items() if not ok]
        _mark_open(conn, family, run_id, commit, failing)
    return run_id


def _mark_met(conn, family, run_id, commit):
    conn.execute(update(S.done_criteria).where(S.done_criteria.c.family == family).values(
        state="met", met_run=run_id, met_commit=commit, updated_at=feedback.now()))
    parked = 0
    for r in conn.execute(select(S.unknowns.c.id).where(and_(S.unknowns.c.family == family,
                                                              S.unknowns.c.status == "open"))).fetchall():
        conn.execute(update(S.unknowns).where(S.unknowns.c.id == r[0]).values(
            status="parked", reason="not-required-by-corpus", updated_at=feedback.now()))
        feedback.event(conn, "parked", commit, unknown_id=r[0], detail={"run": run_id})
        parked += 1
    for r in conn.execute(select(S.expectations.c.id).where(and_(S.expectations.c.family == family,
                                                                  S.expectations.c.status == "open"))).fetchall():
        conn.execute(update(S.expectations).where(S.expectations.c.id == r[0]).values(
            status="parked", updated_at=feedback.now()))
        feedback.event(conn, "parked", commit, expectation_id=r[0], detail={"run": run_id})
        parked += 1
    return parked


def _mark_open(conn, family, run_id, commit, failing_members):
    """Re-open exactly the items the failing cones rest on (lift_provenance -> claims -> scopes)."""
    conn.execute(update(S.done_criteria).where(S.done_criteria.c.family == family).values(
        state="open", updated_at=feedback.now()))
    cone = set()
    for r in conn.execute(select(S.gate_results.c.failing_claims).where(and_(
            S.gate_results.c.run_id == run_id, S.gate_results.c.passed == False))):  # noqa: E712
        cone.update(r[0] or [])
    reopened = {"claims": 0, "patterns": set(), "unknowns": 0, "expectations": 0}
    scopes = set()
    for cid in sorted(cone):
        c = conn.execute(select(S.claims).where(S.claims.c.id == cid)).fetchone()
        if c is None:
            continue
        c = dict(c._mapping)
        scopes.add(c["scope_id"])
        if c["status"] not in ("refuted", "suspect"):
            feedback._set_claim(conn, cid, status="suspect")
            feedback.event(conn, "suspect", commit, claim_id=cid, detail={"corpus-fail": failing_members, "run": run_id})
            reopened["claims"] += 1
        if c["pattern_id"] and c["pattern_id"] not in reopened["patterns"]:
            feedback.suspect_pattern(conn, c["pattern_id"], commit, reason="corpus-fail", except_claim=cid)
            reopened["patterns"].add(c["pattern_id"])
        feedback.queue_audit(conn, c["family"], c["device"], c["scope_id"], "corpus-fail", commit,
                             priority=c["n_objects"], pattern_id=c["pattern_id"], claim_id=cid)
    if scopes:
        for r in conn.execute(select(S.unknowns.c.id).where(and_(
                S.unknowns.c.scope_id.in_(scopes), S.unknowns.c.status == "parked"))).fetchall():
            conn.execute(update(S.unknowns).where(S.unknowns.c.id == r[0]).values(status="open", updated_at=feedback.now()))
            feedback.event(conn, "reopened", commit, unknown_id=r[0], detail={"run": run_id})
            reopened["unknowns"] += 1
        for r in conn.execute(select(S.expectations.c.id).where(and_(
                S.expectations.c.scope_id.in_(scopes), S.expectations.c.status == "parked"))).fetchall():
            conn.execute(update(S.expectations).where(S.expectations.c.id == r[0]).values(status="open", updated_at=feedback.now()))
            feedback.event(conn, "reopened", commit, expectation_id=r[0], detail={"run": run_id})
            reopened["expectations"] += 1
    reopened["patterns"] = sorted(reopened["patterns"])
    return reopened


def state(conn, family):
    return queries.done_state(conn, family)
