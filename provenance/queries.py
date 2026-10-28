"""Blast-radius and status queries (docs/provenance-schema.md). SQLAlchemy Core only; both dialects.

Every function takes an open Connection and returns plain rows / dicts.
"""
from sqlalchemy import and_, func, or_, select

import schema as S


def _rows(conn, stmt):
    return [dict(r._mapping) for r in conn.execute(stmt)]


# ── by pattern / matcher ─────────────────────────────────────────────────────

def by_pattern(conn, pattern_id):
    """Everything predicted by pattern P: claims + expectations, with the objects at stake."""
    c = _rows(conn, select(S.claims).where(S.claims.c.pattern_id == pattern_id))
    e = _rows(conn, select(S.expectations).where(S.expectations.c.pattern_id == pattern_id))
    return {"pattern_id": pattern_id, "claims": c, "expectations": e,
            "n_objects": sum(r["n_objects"] for r in c) + sum(r["n_objects"] for r in e)}


def by_matcher(conn, matcher_id):
    """Everything a matcher produced: its patterns and its expectations (any status)."""
    p = _rows(conn, select(S.claim_patterns).where(S.claim_patterns.c.matcher_id == matcher_id))
    e = _rows(conn, select(S.expectations).where(S.expectations.c.matcher_id == matcher_id))
    return {"matcher_id": matcher_id, "patterns": p, "expectations": e,
            "n_objects": sum(r["n_objects"] for r in e)}


# ── by evidence ──────────────────────────────────────────────────────────────

def patterns_resting_on(conn, evidence_id):
    return [r[0] for r in conn.execute(
        select(S.pattern_evidence.c.pattern_id).where(and_(
            S.pattern_evidence.c.evidence_id == evidence_id,
            S.pattern_evidence.c.role == "parent")).distinct())]


def resting_on(conn, evidence_id):
    """Claims citing E directly, claims of every pattern fitted on E, expectations supported by E."""
    direct_ids = select(S.claim_evidence.c.claim_id).where(S.claim_evidence.c.evidence_id == evidence_id)
    pats = patterns_resting_on(conn, evidence_id)
    cond = S.claims.c.id.in_(direct_ids)
    if pats:
        cond = or_(cond, S.claims.c.pattern_id.in_(pats))
    claims = _rows(conn, select(S.claims).where(cond))
    exps = []
    if pats:
        exps = _rows(conn, select(S.expectations).where(S.expectations.c.pattern_id.in_(pats)))
    # expectations citing E in supporting_evidence (JSON list) — scanned client-side, portable
    for r in _rows(conn, select(S.expectations).where(S.expectations.c.pattern_id.is_(None))):
        if evidence_id in (r.get("supporting_evidence") or []):
            exps.append(r)
    return {"evidence_id": evidence_id, "patterns": pats, "claims": claims, "expectations": exps}


def flips_if_wrong(conn, evidence_id):
    """Blast radius of E by pattern, plus the lifted objects (per bitstream) resting on those claims."""
    r = resting_on(conn, evidence_id)
    by_pat = {}
    for c in r["claims"]:
        d = by_pat.setdefault(c["pattern_id"] or "(direct)", {"claims": 0, "n_objects": 0})
        d["claims"] += 1
        d["n_objects"] += c["n_objects"]
    for e in r["expectations"]:
        d = by_pat.setdefault(e["pattern_id"] or "(direct)", {"claims": 0, "n_objects": 0})
        d.setdefault("expectations", 0)
        d["expectations"] += 1
        d["n_objects"] += e["n_objects"]
    ids = {c["id"] for c in r["claims"]}
    lifted = {}
    if ids:
        for row in _rows(conn, select(S.lift_provenance)):
            if ids & set(row["claim_ids"] or []):
                lifted.setdefault(row["bitstream"], 0)
                lifted[row["bitstream"]] += 1
    return {"evidence_id": evidence_id, "by_pattern": by_pat, "lifted_objects_by_bitstream": lifted,
            "n_objects": sum(v["n_objects"] for v in by_pat.values())}


# ── expectations / unknowns ──────────────────────────────────────────────────

def open_expectations(conn, family, limit=50, device=None):
    """Open expectations ranked by objects at stake."""
    stmt = select(S.expectations).where(and_(S.expectations.c.family == family,
                                             S.expectations.c.status == "open"))
    if device:
        stmt = stmt.where(S.expectations.c.device == device)
    return _rows(conn, stmt.order_by(S.expectations.c.n_objects.desc()).limit(limit))


def _expectation_covers_unknown():
    """Join condition: an open expectation whose scope IS the unknown's scope or NARROWS it (scopes.parent)."""
    e, sc = S.expectations, S.scopes
    return and_(e.c.status == "open",
                or_(e.c.scope_id == S.unknowns.c.scope_id,
                    e.c.scope_id.in_(select(sc.c.id).where(sc.c.parent == S.unknowns.c.scope_id))))


def seriously_unknown(conn, family, device=None):
    """Unknowns with NO open expectation on (or inside) their scope (= no hypothesis at all)."""
    e = S.expectations
    sub = select(e.c.id).where(_expectation_covers_unknown()).exists()
    stmt = select(S.unknowns).where(and_(S.unknowns.c.family == family, S.unknowns.c.status == "open", ~sub))
    if device:
        stmt = stmt.where(S.unknowns.c.device == device)
    return _rows(conn, stmt.order_by(S.unknowns.c.n_objects.desc()))


def expected_unknowns(conn, family, device=None):
    """Unknowns that DO have an open expectation on or inside their scope (a hypothesis awaits a specimen)."""
    e = S.expectations
    j = S.unknowns.join(e, _expectation_covers_unknown())
    stmt = select(S.unknowns.c.id.label("unknown_id"), S.unknowns.c.reason, S.unknowns.c.n_objects,
                  e.c.id.label("expectation_id"), e.c.matcher_id, e.c.pattern_id).select_from(j).where(
        and_(S.unknowns.c.family == family, S.unknowns.c.status == "open"))
    if device:
        stmt = stmt.where(S.unknowns.c.device == device)
    return _rows(conn, stmt)


def parked(conn, family):
    u = _rows(conn, select(S.unknowns).where(and_(S.unknowns.c.family == family, S.unknowns.c.status == "parked")))
    e = _rows(conn, select(S.expectations).where(and_(S.expectations.c.family == family,
                                                      S.expectations.c.status == "parked")))
    return {"unknowns": u, "expectations": e}


# ── coverage ─────────────────────────────────────────────────────────────────

def coverage(conn, family, device):
    """tier x status x inventory_class -> sum n_objects over live claims + unknowns."""
    c = S.claims
    out = {}
    for r in conn.execute(select(c.c.inventory_class, c.c.tier, c.c.status, func.sum(c.c.n_objects))
                          .where(and_(c.c.family == family, c.c.device == device))
                          .group_by(c.c.inventory_class, c.c.tier, c.c.status)):
        out[(r[0] or "-", r[1], r[2])] = int(r[3] or 0)
    u = S.unknowns
    for r in conn.execute(select(u.c.inventory_class, u.c.status, func.sum(u.c.n_objects))
                          .where(and_(u.c.family == family, u.c.device == device))
                          .group_by(u.c.inventory_class, u.c.status)):
        out[(r[0] or "-", "unknown", r[1])] = out.get((r[0] or "-", "unknown", r[1]), 0) + int(r[2] or 0)
    return out


def tier_status_counts(conn, family):
    c = S.claims
    rows = conn.execute(select(c.c.tier, c.c.status, func.count(), func.sum(c.c.n_objects))
                        .where(c.c.family == family).group_by(c.c.tier, c.c.status))
    return [(r[0], r[1], int(r[2]), int(r[3] or 0)) for r in rows]


# ── patterns / audits / conflicts ────────────────────────────────────────────

def suspect_patterns(conn, family):
    return _rows(conn, select(S.claim_patterns).where(and_(S.claim_patterns.c.family == family,
                                                           S.claim_patterns.c.status.in_(("suspect", "refuted")))))


def audit_queue(conn, family, limit=50):
    return _rows(conn, select(S.audits).where(and_(S.audits.c.family == family, S.audits.c.status == "queued"))
                 .order_by(S.audits.c.priority.desc()).limit(limit))


def conflicts(conn, family):
    a = S.claims.alias("a")
    b = S.claims.alias("b")
    j = S.claim_conflicts.join(a, S.claim_conflicts.c.claim_a == a.c.id).join(b, S.claim_conflicts.c.claim_b == b.c.id)
    stmt = select(S.claim_conflicts.c.id, S.claim_conflicts.c.status, a.c.id.label("a_id"), a.c.tier.label("a_tier"),
                  a.c.subject_key, b.c.id.label("b_id"), b.c.tier.label("b_tier"),
                  a.c.n_objects.label("n_objects")).select_from(j).where(a.c.family == family)
    return _rows(conn, stmt)


# ── corpus / done ────────────────────────────────────────────────────────────

def last_gate_run(conn, family):
    r = conn.execute(select(S.gate_runs).where(S.gate_runs.c.family == family)
                     .order_by(S.gate_runs.c.ts.desc(), S.gate_runs.c.id.desc()).limit(1)).fetchone()
    return dict(r._mapping) if r else None


def corpus_state(conn, family):
    """Per member: last result (headline, wrong, passed) from the latest run."""
    run = last_gate_run(conn, family)
    members = _rows(conn, select(S.corpus_members).where(S.corpus_members.c.family == family))
    results = {}
    if run:
        for r in _rows(conn, select(S.gate_results).where(S.gate_results.c.run_id == run["id"])):
            results.setdefault(r["member_id"], []).append(r)
    out = []
    for m in members:
        rs = results.get(m["id"], [])
        out.append({"member": m["name"], "kind": m["kind"], "required": bool(m["required"]),
                    "scored": bool(rs), "passed": bool(rs) and all(r["passed"] for r in rs),
                    "wrong": sum(r["wrong"] for r in rs), "missing": sum(r["missing"] for r in rs),
                    "extra": sum(r["extra"] for r in rs), "matched": sum(r["matched"] for r in rs),
                    "categories": {r["category"]: r["headline"] for r in rs}})
    return {"family": family, "run": run, "members": out}


def done_state(conn, family):
    r = conn.execute(select(S.done_criteria).where(S.done_criteria.c.family == family)).fetchone()
    crit = dict(r._mapping) if r else None
    cs = corpus_state(conn, family)
    req = [m for m in cs["members"] if m["required"]]
    met_now = bool(req) and all(m["scored"] and m["passed"] for m in req)
    return {"family": family, "criterion": crit, "required": len(req),
            "passing": sum(1 for m in req if m["scored"] and m["passed"]),
            "unscored": sum(1 for m in req if not m["scored"]), "met_now": met_now,
            "state": crit["state"] if crit else "no-criterion"}
