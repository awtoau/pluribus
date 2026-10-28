#!/usr/bin/env python3.15t
"""Provenance framework status: tier x status, expectations, conflicts, suspect patterns, audits, corpus, done.

  python3.15t scripts/framework_status.py                      # the DB PLURIBUS_SQLITE_PATH names
  python3.15t scripts/framework_status.py --db databases/cycloneiv/gx150.db
  python3.15t scripts/framework_status.py --all                # every kept DB under databases/
  python3.15t scripts/framework_status.py --json               # machine-readable

One database per family: each file reports its own families. Read-only. Log: tmp/logs/framework_status.log
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import db                                   # noqa: E402
import dbtools                              # noqa: E402
import schema as S                          # noqa: E402
from provenance import queries as Q         # noqa: E402

log = logging.getLogger("framework_status")


def status_of(conn):
    out = {"families": []}
    have = {r[0] for r in conn.execute(select(S.families.c.id))}
    for fam in sorted(have):
        devices = [r[0] for r in conn.execute(select(S.devices.c.name).where(S.devices.c.family == fam))]
        f = {"family": fam, "devices": devices,
             "tier_status": [{"tier": t, "status": s, "claims": n, "objects": o} for t, s, n, o in Q.tier_status_counts(conn, fam)],
             "evidence": {k: n for k, n in conn.execute(select(S.evidence.c.kind, func.count()).where(S.evidence.c.family == fam)
                                                        .group_by(S.evidence.c.kind))},
             "patterns": {s: n for s, n in conn.execute(select(S.claim_patterns.c.status, func.count())
                                                        .where(S.claim_patterns.c.family == fam).group_by(S.claim_patterns.c.status))},
             "open_expectations": [{"id": e["id"], "subject": e["subject_key"], "matcher": e["matcher_id"], "pattern": e["pattern_id"],
                                    "objects": e["n_objects"], "confidence": e["confidence"]}
                                   for e in Q.open_expectations(conn, fam, limit=10)],
             "n_open_expectations": sum(1 for _ in Q.open_expectations(conn, fam, limit=10**9)),
             "seriously_unknown": [{"id": u["id"], "subject": u["subject_key"], "reason": u["reason"], "objects": u["n_objects"],
                                    "class": u["inventory_class"]} for u in Q.seriously_unknown(conn, fam)],
             "expected_unknowns": len(Q.expected_unknowns(conn, fam)),
             "never_exercised": conn.execute(select(func.count()).select_from(S.claims).where(
                 (S.claims.c.family == fam) & (S.claims.c.tier == "never-exercised"))).scalar(),
             "parked": {k: len(v) for k, v in Q.parked(conn, fam).items()},
             "conflicts": [c for c in Q.conflicts(conn, fam) if c["status"] == "open"],
             "suspect_patterns": [p["id"] for p in Q.suspect_patterns(conn, fam)],
             "audit_queue": [{"id": a["id"], "pattern": a["pattern_id"], "reason": a["reason"], "priority": a["priority"]}
                             for a in Q.audit_queue(conn, fam, limit=10)],
             "n_audit_queue": sum(1 for _ in Q.audit_queue(conn, fam, limit=10**9)),
             "corpus": Q.corpus_state(conn, fam),
             "done": Q.done_state(conn, fam)}
        out["families"].append(f)
    return out


def print_status(path, st):
    print(f"== {path}")
    if not st["families"]:
        print("  (no families registered; run scripts/claims_register.py --family <f>)")
    for f in st["families"]:
        print(f"-- family {f['family']}  devices {f['devices']}")
        print("   tier x status (claims / objects):")
        for r in sorted(f["tier_status"], key=lambda r: (-r["objects"], r["tier"])):
            print(f"     {r['tier']:18s} {r['status']:21s} {r['claims']:7d} {r['objects']:14,d}")
        print(f"   evidence: {f['evidence']}")
        print(f"   patterns: {f['patterns']}  suspect: {f['suspect_patterns']}")
        print(f"   expectations open: {f['n_open_expectations']}  (top: " +
              "; ".join(f"{e['subject']} by {e['pattern'] or e['matcher']} {e['objects']:,}" for e in f["open_expectations"][:3]) + ")")
        su = f["seriously_unknown"]
        print(f"   seriously unknown (no hypothesis): {len(su)} rows, {sum(u['objects'] for u in su):,} objects; "
              f"expected-by (unknown with an open expectation): {f['expected_unknowns']}; never-exercised: {f['never_exercised']}; "
              f"parked: {f['parked']}")
        for u in su[:6]:
            print(f"     {u['class'] or '-':3s} {u['subject'] or '':40s} {u['reason']:10s} {u['objects']:14,d}")
        print(f"   conflicts open: {len(f['conflicts'])}  audit queue: {f['n_audit_queue']}")
        c = f["corpus"]
        req = [m for m in c["members"] if m["required"]]
        print(f"   corpus: {len(c['members'])} members ({len(req)} required); last run: "
              f"{(c['run'] or {}).get('script')} @ {(c['run'] or {}).get('commit', '')[:9]} passed={(c['run'] or {}).get('passed')}")
        fails = [m for m in req if m["scored"] and not m["passed"]]
        uns = [m for m in req if not m["scored"]]
        print(f"     required passing {f['done']['passing']}/{len(req)}; failing {len(fails)}; unscored {len(uns)}")
        for m in fails[:5]:
            print(f"     FAIL {m['member']}: wrong {m['wrong']} missing {m['missing']} extra {m['extra']} matched {m['matched']}")
        d = f["done"]
        print(f"   done criterion: state={d['state']}  met_now={d['met_now']}"
              + ("  (no required corpus member declared: declare the gate set first)" if not req else ""))


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(REPO / "tmp/logs/framework_status.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    paths = list(dbtools.kept().values()) if a.all else [a.db or db._SQPATH]
    out = {}
    for p in paths:
        if not os.path.exists(p):
            print(f"== {p}: missing")
            continue
        eng = create_engine(f"sqlite:///file:{os.path.abspath(p)}?mode=ro&uri=true")
        try:
            with eng.connect() as conn:
                have = {r[0] for r in conn.execute(select(func.count()).select_from(S.families))} if \
                    conn.dialect.has_table(conn, "families") else None
                if have is None:
                    print(f"== {p}: no provenance tables (pre-framework database)")
                    continue
                st = status_of(conn)
        except Exception as e:  # a stale snapshot without the tables
            print(f"== {p}: cannot read ({e.__class__.__name__}: {str(e)[:80]})")
            continue
        out[p] = st
        if not a.json:
            print_status(p, st)
        log.info("%s: %s", p, json.dumps({f["family"]: f["done"] for f in st["families"]}, default=str))
    if a.json:
        print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
