#!/usr/bin/env python3
"""Reconcile databases/cycloneiv/gx150.db with corpus designs deleted from disk (#174).

- Gone set = tmp/ignored_placement_designs.txt + designs of tmp/odd_designs.json + every postfit_builds design with no corpus dir.
- Dry-run by default; --apply backs up first (sqlite backup API + integrity_check), then deletes in ONE transaction.
- Deleted: specimen-pair evidence whose base or spec build is gone (+ link rows), corpus_builds / postfit_builds of gone designs.
- gate_runs and gate_results are kept; a corpus member referenced by gate_results stays with required=0, build_id NULL,
  kind='deleted-design'; unreferenced members are deleted.
- Next: claims_register.py, progress_ledger.py, provenance_export.py.  Log: tmp/logs/cycloneiv_retire_deleted_designs.log
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def repo():
    if os.environ.get("PLURIBUS_REPO"):
        return Path(os.environ["PLURIBUS_REPO"])
    try:
        return Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    except Exception:
        return Path(__file__).resolve().parent.parent


REPO = repo()
LOG = REPO / "tmp/logs/cycloneiv_retire_deleted_designs.log"
DB = Path(os.environ.get("PLURIBUS_SQLITE_PATH") or REPO / "databases/cycloneiv/gx150.db")
CORPUS = REPO / "corpus/cycloneiv"


def log(m):
    print(m)
    with open(LOG, "a") as f:
        f.write(m + "\n")


def n(c, sql, *a):
    return c.execute(sql, a).fetchone()[0]


def gone_names(c):
    g = set((REPO / "tmp/ignored_placement_designs.txt").read_text().split())
    g |= {r[0] for r in json.loads((REPO / "tmp/odd_designs.json").read_text())}
    have = set(os.listdir(CORPUS))
    g |= {r[0] for r in c.execute("SELECT design FROM postfit_builds") if r[0] not in have}
    return g - have


def backup():
    dst = DB.parent / "backup" / f"gx150-{datetime.now():%Y%m%d-%H%M%S}-pre-deleted-designs.db"
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    src.backup(out)
    ok = out.execute("PRAGMA integrity_check").fetchone()[0]
    out.close()
    src.close()
    log(f"backup {dst} integrity_check={ok}")
    return ok == "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log(f"mode={'APPLY' if a.apply else 'dry-run'} db={DB}")
    if a.apply and not backup():
        return 2
    c = sqlite3.connect(DB, isolation_level=None, timeout=60)
    c.execute("PRAGMA foreign_keys=OFF")
    gone = gone_names(c)
    c.execute("CREATE TEMP TABLE g(design TEXT PRIMARY KEY)")
    c.executemany("INSERT INTO g VALUES (?)", [(x,) for x in gone])
    c.execute("CREATE TEMP TABLE r_pb AS SELECT id FROM postfit_builds WHERE design IN (SELECT design FROM g)")
    c.execute("CREATE TEMP TABLE r_cb AS SELECT id FROM corpus_builds WHERE design IN (SELECT design FROM g)")
    c.execute("CREATE TEMP TABLE r_ev AS SELECT id FROM evidence WHERE build_base IN (SELECT id FROM r_pb) OR build_spec IN (SELECT id FROM r_pb)")
    mem = [r[0] for r in c.execute("SELECT id, name, build_id FROM corpus_members").fetchall()
           if r[1].split("@")[0] in gone or r[2] in {x[0] for x in c.execute("SELECT id FROM r_pb")}]
    c.execute("CREATE TEMP TABLE r_mem(id INTEGER PRIMARY KEY)")
    c.executemany("INSERT INTO r_mem VALUES (?)", [(i,) for i in mem])
    kinds = dict(c.execute("SELECT e.kind, count(*) FROM evidence e JOIN r_ev USING(id) GROUP BY 1").fetchall())
    refd = n(c, "SELECT count(*) FROM r_mem WHERE id IN (SELECT member_id FROM gate_results)")
    got = {
        "gone designs": len(gone), "postfit_builds": n(c, "SELECT count(*) FROM r_pb"),
        "corpus_builds": n(c, "SELECT count(*) FROM r_cb"), "evidence": n(c, "SELECT count(*) FROM r_ev"),
        "evidence by kind": kinds,
        "claim_evidence": n(c, "SELECT count(*) FROM claim_evidence WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "pattern_evidence": n(c, "SELECT count(*) FROM pattern_evidence WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "evidence_scopes": n(c, "SELECT count(*) FROM evidence_scopes WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "corpus_members": n(c, "SELECT count(*) FROM r_mem"),
        "  of which referenced by gate_results (kept, marked)": refd,
    }
    refs = {
        "claim_events": n(c, "SELECT count(*) FROM claim_events WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "audits": n(c, "SELECT count(*) FROM audits WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "unknowns": n(c, "SELECT count(*) FROM unknowns WHERE absence_evidence IN (SELECT id FROM r_ev)"),
        "expectations": n(c, "SELECT count(*) FROM expectations WHERE resolved_evidence IN (SELECT id FROM r_ev)"),
        "device_pins": n(c, "SELECT count(*) FROM device_pins WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "evidence from kept builds": n(c, "SELECT count(*) FROM evidence WHERE kind='specimen-pair' AND build_base IS NULL AND build_spec IS NULL"),
        "gate_runs": n(c, "SELECT count(*) FROM gate_runs"),
    }
    log(f"to delete: {got}")
    log(f"derived refs to retired evidence (rebuilt by claims_register): {refs}")
    if not a.apply:
        log("dry-run: nothing deleted")
        return 0
    ids = [r[0] for r in c.execute("SELECT id FROM gate_runs ORDER BY id")]
    ngr = n(c, "SELECT count(*) FROM gate_results")
    c.execute("BEGIN IMMEDIATE")
    try:
        for t, col in (("claim_events", "evidence_id"), ("audits", "evidence_id"), ("claim_evidence", "evidence_id"),
                       ("pattern_evidence", "evidence_id"), ("evidence_scopes", "evidence_id")):
            c.execute(f"DELETE FROM {t} WHERE {col} IN (SELECT id FROM r_ev)")
        c.execute("UPDATE unknowns SET absence_evidence=NULL WHERE absence_evidence IN (SELECT id FROM r_ev)")
        c.execute("UPDATE expectations SET resolved_evidence=NULL WHERE resolved_evidence IN (SELECT id FROM r_ev)")
        c.execute("DELETE FROM evidence WHERE id IN (SELECT id FROM r_ev)")
        c.execute("UPDATE corpus_members SET required=0, build_id=NULL, kind='deleted-design' "
                  "WHERE id IN (SELECT id FROM r_mem) AND id IN (SELECT member_id FROM gate_results)")
        c.execute("DELETE FROM corpus_members WHERE id IN (SELECT id FROM r_mem) AND id NOT IN (SELECT member_id FROM gate_results)")
        c.execute("DELETE FROM corpus_builds WHERE id IN (SELECT id FROM r_cb)")
        c.execute("DELETE FROM postfit_builds WHERE id IN (SELECT id FROM r_pb)")
        if [r[0] for r in c.execute("SELECT id FROM gate_runs ORDER BY id")] != ids or n(c, "SELECT count(*) FROM gate_results") != ngr:
            raise RuntimeError("gate records changed")
        c.execute("COMMIT")
    except Exception as e:
        c.execute("ROLLBACK")
        log(f"ROLLED BACK: {e}")
        return 3
    log(f"after: evidence={n(c, 'SELECT count(*) FROM evidence')} corpus_members={n(c, 'SELECT count(*) FROM corpus_members')} "
        f"postfit_builds={n(c, 'SELECT count(*) FROM postfit_builds')} gate_runs={len(ids)} gate_results={ngr}")
    log(f"integrity_check: {c.execute('PRAGMA integrity_check').fetchone()[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
