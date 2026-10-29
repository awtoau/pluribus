"""Coverage tier of an inventory class, COMPUTED from the claims/evidence in the DB (never hand-set).

Rule (docs/provenance-and-feedback.md "Status", docs/recovery-process.md "Patterns and certainty"):
  refuted    any evidence row with role 'refute' inside the class claim's scope
  suspect    any evidence row with role 'conflict' (a refuted sibling / two exact sources disagree)
  verified   an exact oracle-compare row confirms the class claim
  measured   no pattern: exact evidence rows (specimen-pair / roundtrip / audit) back the claim directly
  sampled    pattern-predicted claim confirmed at >= N distinct scopes (N = 3 for a 1-D law, 5 for 2-D), the extremes
             of every axis included, zero refutations/conflicts   (verified-by-sampling; never 'measured')
  predicted  pattern-predicted claim below that bar
  statistical  last-resort statistical claim ('statistical, unverified'): its own tier, never merged into predicted
  decoded    vendor-decoded claim with no exact evidence (decoded-untested)
  unknown    nothing
Class claim = the claim with subject_key 'CLASS:<id>' and inventory_class <id>; evidence links in claim_evidence with
role parent | confirm | direct | refute | conflict.  Scope of a row: meta.tile / meta.site / name 'x<c>_y<r>' / source_ref '<c>x<r>'.
"""
import json
import re

from sqlalchemy import select

import schema as S
from provenance import tiers

EXACT_KINDS = ("specimen-pair", "oracle-compare", "roundtrip", "audit")
TIERS_OUT = ("verified", "measured", "sampled", "predicted", "statistical", "decoded", "suspect", "refuted", "unknown")


def scope_of(result, name, source_ref):
    """Position (x, y) of an evidence row, or None when it carries none."""
    meta = (result or {}).get("meta", {}) if isinstance(result, dict) else {}
    for k in ("tile", "site"):
        v = meta.get(k)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return int(v[0]), int(v[1])
    for s, pat in ((name, r"_x(\d+)_y(\d+)"), (source_ref, r"_x(\d+)_y(\d+)"), (source_ref, r"_(\d+)x(\d+)\b")):
        m = re.search(pat, s or "")
        if m:
            return int(m[1]), int(m[2])
    if source_ref and "forced_lab" in source_ref and not re.search(r"_\d+x\d+", source_ref):
        return 10, 10          # the unsuffixed forced-LAB file is the X10Y10 grid
    if (name or "").startswith("gxm9k_"):
        return 23, 40          # M9K specimens without a site tag sit at the reference site M9K_X23_Y40
    return None


def sampling_bar(law, scopes):
    """THE sampling rule (single source; provenance/feedback.py graduates by it too).
    -> (ok, need, dims, why).  scopes = set of (x, y) positions of distinct confirming scopes.
    N = 3 (1-D) / 5 (2-D) distinct scopes, extremes of every declared axis included; a 2-D law with no axes never passes."""
    law = law or {}
    dims = int(law.get("dims", 2))
    need = tiers.SAMPLING_N[1 if dims == 1 else 2]
    axes = law.get("axes") or {}
    if dims == 2 and not (axes.get("x") and axes.get("y")):
        return False, need, dims, "2-D law declares no axes (extremes cannot be checked)"
    miss = []
    for ai, ax in enumerate(("x", "y")[:dims]):
        lo_hi = axes.get(ax)
        if not lo_hi:
            continue
        vals = {s[ai] for s in scopes}
        miss += [f"{ax}={e}" for e in (lo_hi[0], lo_hi[1]) if e not in vals]
    if len(scopes) < need:
        return False, need, dims, f"{len(scopes)} distinct scopes < {need} ({dims}-D)"
    if miss:
        return False, need, dims, "extremes missing: " + ", ".join(miss)
    return True, need, dims, ""


def class_verdict(conn, family, device, cls):
    """-> dict(tier, n, misses, rule).  n = distinct scopes (pattern) or exact rows (measured); misses = refute + conflict rows."""
    c = conn.execute(select(S.claims).where((S.claims.c.family == family) & (S.claims.c.device == device) &
                                            (S.claims.c.subject_key == f"CLASS:{cls}"))).fetchone()
    if c is None:
        return dict(tier="unknown", n=0, misses=0, rule="no class claim in the DB")
    c = c._mapping
    rows = conn.execute(select(S.claim_evidence.c.role, S.evidence.c.kind, S.evidence.c.name, S.evidence.c.source_ref,
                               S.evidence.c.result).select_from(S.claim_evidence.join(
                                   S.evidence, S.evidence.c.id == S.claim_evidence.c.evidence_id))
                        .where(S.claim_evidence.c.claim_id == c["id"])).fetchall()
    by_role = {}
    for role, kind, name, ref, result in rows:
        by_role.setdefault(role, []).append((kind, scope_of(result, name, ref), ((result or {}).get("meta") or {}).get("group_key")))
    miss_r, miss_c = len(by_role.get("refute", [])), len(by_role.get("conflict", []))
    exact = lambda L: [x for x in L if x[0] in EXACT_KINDS]   # noqa: E731
    n_exact = sum(len(exact(by_role.get(r, []))) for r in ("direct", "parent", "confirm"))
    if miss_r:
        return dict(tier="refuted", n=n_exact, misses=miss_r + miss_c, rule=f"{miss_r} refuting evidence row(s) in scope -> refuted")
    if miss_c:
        return dict(tier="suspect", n=n_exact, misses=miss_c,
                    rule=f"{miss_c} conflicting exact row(s) (sibling refuted / sources disagree) -> suspect")
    if any(x[0] == "oracle-compare" for x in by_role.get("confirm", []) + by_role.get("direct", [])):
        return dict(tier="verified", n=n_exact, misses=0, rule="exact oracle-compare row confirms the class claim")
    pat = None
    if c["pattern_id"]:
        pat = conn.execute(select(S.claim_patterns.c.law).where(S.claim_patterns.c.id == c["pattern_id"])).scalar()
        pat = pat if isinstance(pat, dict) else json.loads(pat or "{}")
    if pat is None:
        if c["tier"] == "measured" and n_exact:
            return dict(tier="measured", n=n_exact, misses=0, rule=f"{n_exact} exact evidence row(s), no pattern")
        if c["tier"] == "vendor-decoded":
            return dict(tier="decoded", n=n_exact, misses=0, rule="vendor decode, no exact evidence at the cells")
        if c["tier"] == "statistical":
            return dict(tier="statistical", n=n_exact, misses=0, rule="statistical claim (last resort), unverified")
        if c["tier"] == "pattern-predicted":
            return dict(tier="predicted", n=n_exact, misses=0, rule="pattern-predicted claim, no pattern bar met")
        return dict(tier="unknown", n=n_exact, misses=0, rule="nothing")
    rows_ = [x for role in ("parent", "confirm") for x in exact(by_role.get(role, []))]
    if pat.get("min_rows_per_group"):
        # 'constant per group' law: a single-row group is not constancy evidence; it counts toward no scope
        per = {}
        for _k, _s, g in rows_:
            per[g] = per.get(g, 0) + 1
        rows_ = [x for x in rows_ if x[2] is not None and per[x[2]] >= int(pat["min_rows_per_group"])]
        groups = len({x[2] for x in rows_})
    else:
        groups = None
    scopes = {s for k, s, _g in rows_ if s is not None}
    ok, need, dims, why = sampling_bar(pat, scopes)
    if ok:
        return dict(tier="sampled", n=len(scopes), misses=0,
                    rule=f"pattern confirmed at {len(scopes)} distinct scopes >= {need} ({dims}-D), extremes included, 0 refutations"
                    + (f"; {groups} groups with >= {pat['min_rows_per_group']} rows" if groups is not None else ""))
    return dict(tier="predicted", n=len(scopes), misses=0, rule=f"pattern below the sampling bar: {why}"
                + (f" ({groups} groups with >= {pat['min_rows_per_group']} rows)" if groups is not None else ""))
