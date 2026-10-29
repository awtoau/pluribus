#!/usr/bin/env python3
"""Retire the DB rows of the banned Cyclone IV coordinate model from databases/cycloneiv/gx150.db (#165).

- Dry-run by default; --apply deletes, in ONE transaction, only if every count matches EXPECTED.
- Row list: https://github.com/awtoau/pluribus/issues/165#issuecomment-6499657750
- Kept: raw specimen-pair evidence, gate_runs, gate_results, the 3 `ddb:*` vendor-ddb-v1 claims.
- Log: tmp/logs/cycloneiv_retire_db_rows.log
"""
import argparse, os, sqlite3, subprocess, sys
from pathlib import Path

def repo():
    if os.environ.get("PLURIBUS_REPO"):
        return Path(os.environ["PLURIBUS_REPO"])
    try:
        return Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    except Exception:
        return Path(__file__).resolve().parent.parent

REPO = repo()
LOG = REPO / "tmp/logs/cycloneiv_retire_db_rows.log"
DB = REPO / "databases/cycloneiv/gx150.db"

CLASSES = ("2a", "2b", "2h", "2h-fd", "2h-col")
PATTERNS = ("afx-mirror-v1", "hop-shift-v1", "r4-framedist-v1", "r4-percol-v1")
MATCHERS = PATTERNS + ("vote-v1",)
# evidence ids (from the 2026-10-30 inspection): 3 R4 per-column tables, hop-override oracle-compare, phys_map + li_map JSON
EVIDENCE_NAMES = (
    ("derived-table", "scripts/cycloneiv_r4_relcol.py coltable", 3),
    ("oracle-compare", "scripts/cycloneiv_ddb_trace.py", 1),
    ("vendor-decode", "lifters/data/cycloneiv_ep4cgx150_phys_map.json", 1),
    ("vendor-decode", "lifters/data/cycloneiv_ep4cgx150_li_map.json", 1),
)
# claim set: the 5 classes minus the kept ddb:* vendor-ddb-v1 claims
CLAIM_WHERE = (f"inventory_class IN ({','.join(repr(c) for c in CLASSES)}) AND subject_key NOT LIKE 'ddb:%'")
# counts: comment figures (3,606 claims = 3,609 - 3 kept; links 3,966 incl. 2 hanging off the 3 kept ddb claims -> 3,964)
EXPECTED = {"claims": 3606, "claim_evidence": 3964, "claim_patterns": 4, "matchers": 5, "evidence": 6}

def log(m):
    print(m)
    with open(LOG, "a") as f:
        f.write(m + "\n")

def n(c, sql, *a):
    return c.execute(sql, a).fetchone()[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, isolation_level=None)
    c.execute("PRAGMA foreign_keys=OFF")
    pin = ",".join("?" * len(PATTERNS)); min_ = ",".join("?" * len(MATCHERS))
    c.execute("CREATE TEMP TABLE r_claims AS SELECT id FROM claims WHERE " + CLAIM_WHERE)
    ev_ids = []
    for kind, ref, want in EVIDENCE_NAMES:
        ids = [r[0] for r in c.execute("SELECT id FROM evidence WHERE kind=? AND source_ref=?", (kind, ref))]
        if len(ids) != want:
            log(f"REFUSE: evidence {kind} {ref}: {len(ids)} rows, expected {want}")
            return 2
        ev_ids += ids
    c.execute("CREATE TEMP TABLE r_ev(id INTEGER)")
    c.executemany("INSERT INTO r_ev VALUES (?)", [(i,) for i in ev_ids])
    c.execute(f"CREATE TEMP TABLE r_pat AS SELECT id FROM claim_patterns WHERE id IN ({pin})", PATTERNS)
    got = {
        "claims": n(c, "SELECT count(*) FROM r_claims"),
        "claim_evidence": n(c, "SELECT count(*) FROM claim_evidence WHERE claim_id IN (SELECT id FROM r_claims)"),
        "claim_patterns": n(c, "SELECT count(*) FROM r_pat"),
        "matchers": n(c, f"SELECT count(*) FROM matchers WHERE id IN ({min_})", *MATCHERS),
        "evidence": n(c, "SELECT count(*) FROM r_ev"),
    }
    extra = {
        "claim_events (claim or pattern)": n(c, "SELECT count(*) FROM claim_events WHERE claim_id IN (SELECT id FROM r_claims) OR pattern_id IN (SELECT id FROM r_pat)"),
        "pattern_evidence (pattern)": n(c, "SELECT count(*) FROM pattern_evidence WHERE pattern_id IN (SELECT id FROM r_pat)"),
        "pattern_evidence (evidence)": n(c, "SELECT count(*) FROM pattern_evidence WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "claim_evidence (kept claims -> retired evidence)": n(c, "SELECT count(*) FROM claim_evidence WHERE evidence_id IN (SELECT id FROM r_ev) AND claim_id NOT IN (SELECT id FROM r_claims)"),
        "evidence_scopes (retired evidence)": n(c, "SELECT count(*) FROM evidence_scopes WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "claim_patterns (kept) -> retired matchers": n(c, f"SELECT count(*) FROM claim_patterns WHERE matcher_id IN ({min_}) AND id NOT IN (SELECT id FROM r_pat)", *MATCHERS),
        "claims (kept) -> retired patterns": n(c, "SELECT count(*) FROM claims WHERE pattern_id IN (SELECT id FROM r_pat) AND id NOT IN (SELECT id FROM r_claims)"),
        "expectations -> retired claims/patterns/matchers": n(c, f"SELECT count(*) FROM expectations WHERE claim_id IN (SELECT id FROM r_claims) OR pattern_id IN (SELECT id FROM r_pat) OR matcher_id IN ({min_})", *MATCHERS),
        "audits -> retired claims/patterns": n(c, "SELECT count(*) FROM audits WHERE claim_id IN (SELECT id FROM r_claims) OR pattern_id IN (SELECT id FROM r_pat)"),
        "claim_conflicts -> retired claims": n(c, "SELECT count(*) FROM claim_conflicts WHERE claim_a IN (SELECT id FROM r_claims) OR claim_b IN (SELECT id FROM r_claims)"),
        "claims.superseded_by -> retired claims": n(c, "SELECT count(*) FROM claims WHERE superseded_by IN (SELECT id FROM r_claims)"),
    }
    keep = {t: n(c, f"SELECT count(*) FROM {t}") for t in ("gate_runs", "gate_results")}
    keep_ids = [r[0] for r in c.execute("SELECT id FROM gate_runs ORDER BY id")]
    log(f"mode={'APPLY' if a.apply else 'dry-run'} db={DB}")
    log(f"to delete: {got}  expected: {EXPECTED}")
    log(f"dependents: {extra}")
    log(f"gate_runs/gate_results before: {keep}")
    bad = [k for k in EXPECTED if got[k] != EXPECTED[k]]
    if bad:
        log(f"REFUSE: count mismatch {bad}")
        return 2
    risky = {k: v for k, v in extra.items() if v and not k.startswith(("claim_events", "pattern_evidence"))}
    if risky:
        log(f"REFUSE: unexpected dependents (would orphan/need decision): {risky}")
        return 2
    if not a.apply:
        log("dry-run: nothing deleted")
        return 0
    tabs = ["claims", "claim_evidence", "claim_events", "pattern_evidence", "claim_patterns", "matchers", "evidence", "address_spaces", "scopes"]
    before = {t: n(c, f"SELECT count(*) FROM {t}") for t in tabs}
    c.execute("BEGIN")
    try:
        c.execute("DELETE FROM claim_events WHERE claim_id IN (SELECT id FROM r_claims) OR pattern_id IN (SELECT id FROM r_pat)")
        c.execute("DELETE FROM pattern_evidence WHERE pattern_id IN (SELECT id FROM r_pat) OR evidence_id IN (SELECT id FROM r_ev)")
        c.execute("DELETE FROM claim_evidence WHERE claim_id IN (SELECT id FROM r_claims) OR evidence_id IN (SELECT id FROM r_ev)")
        c.execute("DELETE FROM claims WHERE id IN (SELECT id FROM r_claims)")
        c.execute("DELETE FROM claim_patterns WHERE id IN (SELECT id FROM r_pat)")
        c.execute(f"DELETE FROM matchers WHERE id IN ({min_})", MATCHERS)
        c.execute("DELETE FROM evidence WHERE id IN (SELECT id FROM r_ev)")
        # post-conditions inside the transaction
        after_keep = {t: n(c, f"SELECT count(*) FROM {t}") for t in ("gate_runs", "gate_results")}
        if after_keep != keep or [r[0] for r in c.execute("SELECT id FROM gate_runs ORDER BY id")] != keep_ids:
            raise RuntimeError(f"gate records changed: {after_keep}")
        if n(c, "SELECT count(*) FROM claims WHERE subject_key LIKE 'ddb:%'") != 3:
            raise RuntimeError("kept ddb:* claims != 3")
        c.execute("COMMIT")
    except Exception as e:
        c.execute("ROLLBACK")
        log(f"ROLLED BACK: {e}")
        return 3
    after = {t: n(c, f"SELECT count(*) FROM {t}") for t in tabs}
    for t in tabs:
        log(f"  {t}: {before[t]} -> {after[t]}")
    log(f"gate_runs/gate_results after: {after_keep}  ids={keep_ids}")
    log(f"integrity_check: {c.execute('PRAGMA integrity_check').fetchone()[0]}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
