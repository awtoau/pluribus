#!/usr/bin/env python3
"""Remove the rows of dies other than EP4CGX150 from databases/cycloneiv/gx150.db (#173).

- Dry-run by default; --apply backs the DB up first (sqlite backup API, integrity_check), then deletes in ONE transaction.
- Removed: device_pins of other dies, the 12 other-die third-party-image corpus members, their gate_results and image-hit evidence (+ link rows).
- Kept: every gate_runs id, all EP4CGX150 rows (all packages), the 5 GX150 third-party images.
- Log: tmp/logs/cycloneiv_retire_other_dies.log
"""
import argparse
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
LOG = REPO / "tmp/logs/cycloneiv_retire_other_dies.log"
DB = Path(os.environ.get("PLURIBUS_SQLITE_PATH") or REPO / "databases/cycloneiv/gx150.db")
KEEP_PREFIX = "EP4CGX150"
OTHER_IMAGES = ("neptuno_menu", "neptuno_nes", "neptuno_minimig", "sidi_iremm92", "joker_tv", "ucore_ep4ce6",
                "cam_isp_ep4ce6", "scope_ep4ce10", "basic52_ep4ce15", "bitcoin_de2_115", "d8m_tracker_de2_115",
                "sidi_neogeo")


def log(m):
    print(m)
    with open(LOG, "a") as f:
        f.write(m + "\n")


def n(c, sql, *a):
    return c.execute(sql, a).fetchone()[0]


def backup():
    dst = DB.parent / "backup" / f"gx150-{datetime.now():%Y%m%d-%H%M%S}-pre-onedie.db"
    dst.parent.mkdir(exist_ok=True)
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
        log("REFUSE: backup integrity_check failed")
        return 2
    c = sqlite3.connect(DB, isolation_level=None, timeout=60)
    c.execute("PRAGMA foreign_keys=OFF")
    ph = ",".join("?" * len(OTHER_IMAGES))
    c.execute(f"CREATE TEMP TABLE r_mem AS SELECT id FROM corpus_members WHERE kind='third-party-image' AND name IN ({ph})", OTHER_IMAGES)
    c.execute(f"CREATE TEMP TABLE r_ev AS SELECT id FROM evidence WHERE kind='image-hit' AND name IN ({ph})", OTHER_IMAGES)
    c.execute("CREATE TEMP TABLE r_pins AS SELECT id FROM device_pins WHERE part NOT LIKE ?", (KEEP_PREFIX + "%",))
    c.execute("CREATE TEMP TABLE r_bld AS SELECT id FROM postfit_builds WHERE device NOT LIKE ?", (KEEP_PREFIX + "%",))
    got = {
        "corpus_members": n(c, "SELECT count(*) FROM r_mem"),
        "gate_results": n(c, "SELECT count(*) FROM gate_results WHERE member_id IN (SELECT id FROM r_mem)"),
        "evidence": n(c, "SELECT count(*) FROM r_ev"),
        "claim_evidence": n(c, "SELECT count(*) FROM claim_evidence WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "pattern_evidence": n(c, "SELECT count(*) FROM pattern_evidence WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "evidence_scopes": n(c, "SELECT count(*) FROM evidence_scopes WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "device_pins": n(c, "SELECT count(*) FROM r_pins"),
        "postfit_builds (other device)": n(c, "SELECT count(*) FROM r_bld"),
    }
    refs = {
        "claim_events -> r_ev": n(c, "SELECT count(*) FROM claim_events WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "audits -> r_ev": n(c, "SELECT count(*) FROM audits WHERE evidence_id IN (SELECT id FROM r_ev)"),
        "unknowns -> r_ev": n(c, "SELECT count(*) FROM unknowns WHERE absence_evidence IN (SELECT id FROM r_ev)"),
        "expectations -> r_ev": n(c, "SELECT count(*) FROM expectations WHERE resolved_evidence IN (SELECT id FROM r_ev)"),
        "other-device claims/scopes/expectations": sum(n(c, f"SELECT count(*) FROM {t} WHERE device NOT LIKE ?", KEEP_PREFIX + "%")
                                                       for t in ("claims", "scopes", "expectations", "unknowns", "coverage_ledger")),
        "gate_runs": n(c, "SELECT count(*) FROM gate_runs"),
    }
    log(f"to delete: {got}")
    log(f"references / kept: {refs}")
    if got["postfit_builds (other device)"] or refs["other-device claims/scopes/expectations"]:
        log("REFUSE: other-device build/claim/scope rows exist; extend the script")
        return 2
    risky = {k: v for k, v in refs.items() if v and k.endswith("-> r_ev")}
    if risky:
        log(f"REFUSE: unexpected references {risky}")
        return 2
    if not a.apply:
        log("dry-run: nothing deleted")
        return 0
    ids_before = [r[0] for r in c.execute("SELECT id FROM gate_runs ORDER BY id")]
    tabs = ["corpus_members", "gate_results", "evidence", "claim_evidence", "pattern_evidence", "evidence_scopes", "device_pins"]
    before = {t: n(c, f"SELECT count(*) FROM {t}") for t in tabs}
    c.execute("BEGIN IMMEDIATE")
    try:
        c.execute("DELETE FROM gate_results WHERE member_id IN (SELECT id FROM r_mem)")
        c.execute("DELETE FROM claim_evidence WHERE evidence_id IN (SELECT id FROM r_ev)")
        c.execute("DELETE FROM pattern_evidence WHERE evidence_id IN (SELECT id FROM r_ev)")
        c.execute("DELETE FROM evidence_scopes WHERE evidence_id IN (SELECT id FROM r_ev)")
        c.execute("DELETE FROM evidence WHERE id IN (SELECT id FROM r_ev)")
        c.execute("DELETE FROM corpus_members WHERE id IN (SELECT id FROM r_mem)")
        c.execute("DELETE FROM device_pins WHERE id IN (SELECT id FROM r_pins)")
        if [r[0] for r in c.execute("SELECT id FROM gate_runs ORDER BY id")] != ids_before:
            raise RuntimeError("gate_runs ids changed")
        if n(c, "SELECT count(*) FROM device_pins WHERE part NOT LIKE ?", KEEP_PREFIX + "%"):
            raise RuntimeError("other-die pins remain")
        c.execute("COMMIT")
    except Exception as e:
        c.execute("ROLLBACK")
        log(f"ROLLED BACK: {e}")
        return 3
    for t in tabs:
        log(f"  {t}: {before[t]} -> {n(c, f'SELECT count(*) FROM {t}')}")
    log(f"integrity_check: {c.execute('PRAGMA integrity_check').fetchone()[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
