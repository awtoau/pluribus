"""The feedback loop (docs/provenance-and-feedback.md section 3) as DB operations.

Every state change writes one claim_events row (append-only). Tier never changes here.
"""
import datetime

from sqlalchemy import and_, insert, select, update

import db
import schema as S
from provenance import tiers


def now():
    return datetime.datetime.now().astimezone()


def event(conn, event_name, commit, claim_id=None, pattern_id=None, expectation_id=None,
          unknown_id=None, evidence_id=None, detail=None):
    tiers.check(event_name, tiers.EVENTS, "event")
    conn.execute(insert(S.claim_events).values(
        claim_id=claim_id, pattern_id=pattern_id, expectation_id=expectation_id, unknown_id=unknown_id,
        event=event_name, evidence_id=evidence_id, commit=commit, ts=now(), detail=detail))


def _claim(conn, claim_id):
    r = conn.execute(select(S.claims).where(S.claims.c.id == claim_id)).fetchone()
    if r is None:
        db.die(f"claim {claim_id} does not exist")
    return dict(r._mapping)


def _pattern(conn, pattern_id):
    r = conn.execute(select(S.claim_patterns).where(S.claim_patterns.c.id == pattern_id)).fetchone()
    if r is None:
        db.die(f"pattern {pattern_id!r} does not exist")
    return dict(r._mapping)


def _evidence_kind(conn, evidence_id):
    r = conn.execute(select(S.evidence.c.kind).where(S.evidence.c.id == evidence_id)).fetchone()
    if r is None:
        db.die(f"evidence {evidence_id} does not exist")
    return r[0]


def _set_claim(conn, claim_id, **vals):
    vals["updated_at"] = now()
    conn.execute(update(S.claims).where(S.claims.c.id == claim_id).values(**vals))


def _set_pattern(conn, pattern_id, **vals):
    vals["updated_at"] = now()
    conn.execute(update(S.claim_patterns).where(S.claim_patterns.c.id == pattern_id).values(**vals))


def queue_audit(conn, family, device, scope_id, reason, commit, priority=0, pattern_id=None,
                claim_id=None, expectation_id=None):
    tiers.check(reason, tiers.AUDIT_REASONS, "audit reason")
    # never a scope already queued / audited for the same pattern
    q = conn.execute(select(S.audits.c.id).where(and_(
        S.audits.c.scope_id == scope_id, S.audits.c.pattern_id == pattern_id,
        S.audits.c.status.in_(("queued", "built", "confirmed"))))).fetchone()
    if q:
        return None
    return conn.execute(insert(S.audits).values(
        family=family, device=device, pattern_id=pattern_id, claim_id=claim_id,
        expectation_id=expectation_id, scope_id=scope_id, priority=priority, reason=reason,
        status="queued", queued_commit=commit, updated_at=now())).inserted_primary_key[0]


def suspect_pattern(conn, pattern_id, commit, evidence_id=None, reason="suspect", except_claim=None):
    """Pattern -> suspect; every claim citing it -> suspect; audits queued for every sibling scope."""
    p = _pattern(conn, pattern_id)
    _set_pattern(conn, pattern_id, status="suspect", refutations=p["refutations"] + 1)
    sib = conn.execute(select(S.claims).where(and_(
        S.claims.c.pattern_id == pattern_id, S.claims.c.status.notin_(("refuted", "superseded"))))).fetchall()
    n_bits = 0
    for r in sib:
        r = dict(r._mapping)
        if r["id"] == except_claim:
            continue
        _set_claim(conn, r["id"], status="suspect")
        event(conn, "suspect", commit, claim_id=r["id"], pattern_id=pattern_id, evidence_id=evidence_id,
              detail={"via": "sibling-refuted"})
        queue_audit(conn, r["family"], r["device"], r["scope_id"], reason, commit,
                    priority=r["n_objects"], pattern_id=pattern_id, claim_id=r["id"])
        n_bits += r["n_objects"]
    exps = conn.execute(select(S.expectations).where(and_(
        S.expectations.c.pattern_id == pattern_id, S.expectations.c.status == "open"))).fetchall()
    for r in exps:
        r = dict(r._mapping)
        queue_audit(conn, r["family"], r["device"], r["scope_id"], reason, commit,
                    priority=r["n_objects"], pattern_id=pattern_id, expectation_id=r["id"])
    event(conn, "suspect", commit, pattern_id=pattern_id, evidence_id=evidence_id,
          detail={"siblings": len(sib), "bits_affected": n_bits, "expectations": len(exps)})
    return {"siblings": len(sib), "bits_affected": n_bits, "expectations": len(exps)}


def refute(conn, claim_id, evidence_id, commit):
    """A specimen inside the claim's scope contradicts it. Negative loop steps a–c."""
    tiers.check(_evidence_kind(conn, evidence_id), tiers.CONFIRMING_KINDS, "refuting evidence kind")
    c = _claim(conn, claim_id)
    _set_claim(conn, claim_id, status="refuted", refutations=c["refutations"] + 1)
    conn.execute(insert(S.claim_evidence).values(claim_id=claim_id, evidence_id=evidence_id, role="refute"))
    event(conn, "refuted", commit, claim_id=claim_id, pattern_id=c["pattern_id"], evidence_id=evidence_id)
    out = {"claim": claim_id, "pattern": c["pattern_id"]}
    if c["pattern_id"]:
        conn.execute(insert(S.pattern_evidence).values(pattern_id=c["pattern_id"], evidence_id=evidence_id,
                                                       role="refute"))
        out.update(suspect_pattern(conn, c["pattern_id"], commit, evidence_id, except_claim=claim_id))
    return out


def _graduate(conn, pattern_id, commit):
    p = _pattern(conn, pattern_id)
    scopes = {r[0] for r in conn.execute(select(S.claim_events.c.detail).where(and_(
        S.claim_events.c.pattern_id == pattern_id, S.claim_events.c.event == "confirmed")))
        for r in [(str((r[0] or {}).get("scope_id")),)]}
    need = tiers.SAMPLING_N.get(int((p["law"] or {}).get("dims", 1)), 3)
    if p["status"] in ("open", "confirmed") and p["refutations"] == 0 and len(scopes) >= need:
        _set_pattern(conn, pattern_id, status="verified-by-sampling")
        for r in conn.execute(select(S.claims.c.id).where(and_(S.claims.c.pattern_id == pattern_id,
                                                                S.claims.c.status.in_(("open", "confirmed"))))):
            _set_claim(conn, r[0], status="verified-by-sampling")
        event(conn, "confirmed", commit, pattern_id=pattern_id, detail={"graduated": "verified-by-sampling",
                                                                        "scopes": len(scopes)})


def confirm(conn, claim_id, evidence_id, commit):
    """A held-out specimen agrees with the claim. Positive loop."""
    tiers.check(_evidence_kind(conn, evidence_id), tiers.CONFIRMING_KINDS, "confirming evidence kind")
    c = _claim(conn, claim_id)
    new_status = "confirmed" if c["status"] in ("open", "confirmed") else c["status"]
    _set_claim(conn, claim_id, status=new_status, confirmations=c["confirmations"] + 1)
    conn.execute(insert(S.claim_evidence).values(claim_id=claim_id, evidence_id=evidence_id, role="confirm"))
    event(conn, "confirmed", commit, claim_id=claim_id, pattern_id=c["pattern_id"], evidence_id=evidence_id,
          detail={"scope_id": c["scope_id"]})
    if c["pattern_id"]:
        p = _pattern(conn, c["pattern_id"])
        _set_pattern(conn, c["pattern_id"], confirmations=p["confirmations"] + 1)
        conn.execute(insert(S.pattern_evidence).values(pattern_id=c["pattern_id"], evidence_id=evidence_id,
                                                       role="confirm"))
        if c["tier"] == "pattern-predicted":
            _graduate(conn, c["pattern_id"], commit)


def clear_pattern(conn, pattern_id, commit):
    """Leave suspect: only when every queued audit confirmed and no open refutation remains."""
    open_audits = conn.execute(select(S.audits.c.id).where(and_(
        S.audits.c.pattern_id == pattern_id, S.audits.c.status.in_(("queued", "built", "refuted"))))).fetchone()
    if open_audits:
        db.die(f"pattern {pattern_id!r} still has unresolved or refuted audits; 'mostly holds' is not an exit")
    _set_pattern(conn, pattern_id, status="confirmed")
    for r in conn.execute(select(S.claims.c.id).where(and_(S.claims.c.pattern_id == pattern_id,
                                                            S.claims.c.status == "suspect"))):
        _set_claim(conn, r[0], status="confirmed")
        event(conn, "cleared", commit, claim_id=r[0], pattern_id=pattern_id)
    event(conn, "cleared", commit, pattern_id=pattern_id)


def confirm_expectation(conn, expectation_id, evidence_id, commit, meaning=None, scope_id=None):
    """A specimen confirms a prediction: the expectation closes and a MEASURED claim is born."""
    tiers.check(_evidence_kind(conn, evidence_id), tiers.CONFIRMING_KINDS, "confirming evidence kind")
    e = conn.execute(select(S.expectations).where(S.expectations.c.id == expectation_id)).fetchone()
    if e is None:
        db.die(f"expectation {expectation_id} does not exist")
    e = dict(e._mapping)
    cid = conn.execute(insert(S.claims).values(
        family=e["family"], device=e["device"], space=e["space"], subject_key=e["subject_key"],
        scope_id=scope_id or e["scope_id"], meaning=meaning if meaning is not None else e["expected"],
        tier="measured", status="confirmed", pattern_id=None, n_objects=e["n_objects"],
        confidence_basis=f"specimen confirmed expectation {expectation_id} ({e['matcher_id']})",
        confirmations=1, created_commit=commit, updated_at=now())).inserted_primary_key[0]
    conn.execute(insert(S.claim_evidence).values(claim_id=cid, evidence_id=evidence_id, role="direct"))
    conn.execute(update(S.expectations).where(S.expectations.c.id == expectation_id).values(
        status="confirmed", resolved_evidence=evidence_id, claim_id=cid, updated_at=now()))
    event(conn, "created", commit, claim_id=cid, evidence_id=evidence_id, expectation_id=expectation_id)
    event(conn, "confirmed", commit, expectation_id=expectation_id, pattern_id=e["pattern_id"],
          evidence_id=evidence_id, detail={"scope_id": e["scope_id"], "claim_id": cid})
    if e["pattern_id"]:
        p = _pattern(conn, e["pattern_id"])
        _set_pattern(conn, e["pattern_id"], confirmations=p["confirmations"] + 1)
        conn.execute(insert(S.pattern_evidence).values(pattern_id=e["pattern_id"], evidence_id=evidence_id,
                                                       role="confirm"))
        _graduate(conn, e["pattern_id"], commit)
    # the unknown this scope carried is promoted
    for r in conn.execute(select(S.unknowns.c.id).where(and_(S.unknowns.c.scope_id == e["scope_id"],
                                                              S.unknowns.c.status != "promoted"))):
        conn.execute(update(S.unknowns).where(S.unknowns.c.id == r[0]).values(status="promoted", updated_at=now()))
        event(conn, "hit", commit, unknown_id=r[0], evidence_id=evidence_id, detail={"claim_id": cid})
    return cid


def refute_expectation(conn, expectation_id, evidence_id, commit, observed=None):
    tiers.check(_evidence_kind(conn, evidence_id), tiers.CONFIRMING_KINDS, "refuting evidence kind")
    e = conn.execute(select(S.expectations).where(S.expectations.c.id == expectation_id)).fetchone()
    if e is None:
        db.die(f"expectation {expectation_id} does not exist")
    e = dict(e._mapping)
    conn.execute(update(S.expectations).where(S.expectations.c.id == expectation_id).values(
        status="refuted", resolved_evidence=evidence_id, updated_at=now()))
    event(conn, "refuted", commit, expectation_id=expectation_id, pattern_id=e["pattern_id"],
          evidence_id=evidence_id, detail={"observed": observed})
    out = {"expectation": expectation_id, "pattern": e["pattern_id"]}
    if e["pattern_id"]:
        conn.execute(insert(S.pattern_evidence).values(pattern_id=e["pattern_id"], evidence_id=evidence_id,
                                                       role="refute"))
        out.update(suspect_pattern(conn, e["pattern_id"], commit, evidence_id))
    return out


def conflict(conn, claim_a, claim_b, commit, detail=None):
    """Two exact-claimed sources disagree: both -> conflict; neither counts as known."""
    a, b = _claim(conn, claim_a), _claim(conn, claim_b)
    if (a["space"], a["subject_key"]) != (b["space"], b["subject_key"]):
        db.die(f"claims {claim_a} and {claim_b} are not on the same subject")
    for cid in (claim_a, claim_b):
        _set_claim(conn, cid, status="conflict")
        event(conn, "conflict", commit, claim_id=cid, detail={"with": claim_b if cid == claim_a else claim_a})
    return conn.execute(insert(S.claim_conflicts).values(
        claim_a=claim_a, claim_b=claim_b, status="open", opened_commit=commit, detail=detail)).inserted_primary_key[0]


def adjudicate(conn, conflict_id, winner, resolution, commit):
    r = conn.execute(select(S.claim_conflicts).where(S.claim_conflicts.c.id == conflict_id)).fetchone()
    if r is None:
        db.die(f"conflict {conflict_id} does not exist")
    r = dict(r._mapping)
    loser = r["claim_b"] if winner == r["claim_a"] else r["claim_a"]
    conn.execute(update(S.claim_conflicts).where(S.claim_conflicts.c.id == conflict_id).values(
        status="adjudicated", winner=winner, resolution=resolution))
    _set_claim(conn, winner, status="confirmed")
    _set_claim(conn, loser, status="refuted")
    event(conn, "cleared", commit, claim_id=winner, detail={"conflict": conflict_id})
    event(conn, "refuted", commit, claim_id=loser, detail={"conflict": conflict_id, "resolution": resolution})


def supersede(conn, old_claim, new_claim, commit):
    """Statistical -> exact replacement: old keeps its tier, status superseded, points at new."""
    o, n = _claim(conn, old_claim), _claim(conn, new_claim)
    if tiers.rank(n["tier"]) > tiers.rank(o["tier"]):
        db.die(f"claim {new_claim} ({n['tier']}) is weaker than {old_claim} ({o['tier']}); cannot supersede")
    _set_claim(conn, old_claim, status="superseded", superseded_by=new_claim)
    event(conn, "superseded", commit, claim_id=old_claim, detail={"by": new_claim})


def effective_tier(conn, claim_id, _seen=None):
    """Weakest-link tier: own tier vs every claim the pattern's parent evidence rests on."""
    _seen = _seen or set()
    if claim_id in _seen:
        return "unknown"
    _seen.add(claim_id)
    c = _claim(conn, claim_id)
    chain = [c["tier"]]
    if c["pattern_id"]:
        parents = [r[0] for r in conn.execute(select(S.pattern_evidence.c.evidence_id).where(and_(
            S.pattern_evidence.c.pattern_id == c["pattern_id"], S.pattern_evidence.c.role == "parent")))]
        for ev in parents:
            for r in conn.execute(select(S.claim_evidence.c.claim_id).where(and_(
                    S.claim_evidence.c.evidence_id == ev, S.claim_evidence.c.role == "direct"))):
                if r[0] != claim_id:
                    chain.append(effective_tier(conn, r[0], _seen))
    # claims whose meaning depends on another claim (e.g. placement via a coord-map) cite it in meaning.depends_on
    for dep in (c["meaning"] or {}).get("depends_on", []) if isinstance(c["meaning"], dict) else []:
        chain.append(effective_tier(conn, dep, _seen))
    return tiers.weakest(chain)
