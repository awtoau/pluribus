#!/usr/bin/env python3.15t
"""Before/after bench for the SQL-bound pipeline stages (reach.py, reach2.py) on a COPY of a kept DB.

  python3.15t scripts/bench_reach_sql.py --db <copy.db> --label FNIRSI --tag before [--workers 8]
  python3.15t scripts/bench_reach_sql.py --compare tmp/bench_reach_sql/before_FNIRSI.json tmp/bench_reach_sql/after_FNIRSI.json

Runs reach.py --replace then reach2.py as child processes (stall-guarded through heavy_guard), records
wall per stage (and the stages' own printed phase times), then an ORDER-INDEPENDENT content hash per
output table (sha256 over rows sorted by their natural key, bitstream-scoped) + row counts.
--compare prints the wall table and dies if any table hash or count differs. Never run on a kept DB.
Results tmp/bench_reach_sql/<tag>_<label>.json; log tmp/logs/bench_reach_sql.log
"""
import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard   # noqa: E402

log = logging.getLogger("bench_reach_sql")
OUT = REPO / "tmp" / "bench_reach_sql"
TABLES = {"reachability": "src, dst, min_hops", "pad_ff_influence": "pad_label, ff_cell, min_hops",
          "reachability_rev": "dst, src, min_hops", "ff_cones": "ff_cell, cone_type, net, min_hops"}
STALL_S = 120          # reach2 prints only per-100-FF progress; ff_cones on V02 is silent ~15 s; 8x margin
OVERALL_S = 3 * 180    # 3x measured cold worst (reach2 V02 48 s + reach 17 s, plus startup)
PHASE_RE = re.compile(r"^\s*(BFS done in|Inserted \d+ rows in|pad_ff_influence:|\s*(reverse|ff_cones)\s+)(.*)$")


def content_hash(db_path, bs_id):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out = {}
    for t, cols in TABLES.items():
        h = hashlib.sha256()
        n = 0
        for row in conn.execute(f"SELECT {cols} FROM {t} WHERE bitstream=? ORDER BY {cols}", (bs_id,)):
            h.update(repr(row).encode())
            h.update(b"\n")
            n += 1
        out[t] = {"rows": n, "sha256": h.hexdigest()[:16]}
    conn.close()
    return out


def run_stage(script, args, env, what):
    cmd = [sys.executable, str(REPO / script)] + args
    t0 = time.perf_counter()
    r = heavy_guard.run_stall_guarded(cmd, what, log, stall_s=STALL_S, overall_s=OVERALL_S, env=env)
    wall = time.perf_counter() - t0
    if r.returncode != 0:
        log.error("%s failed rc=%s\n%s", what, r.returncode, (r.stderr or "")[-800:])
        sys.exit(1)
    phases = {}
    for ln in (r.stdout or "").splitlines():
        m = re.search(r"BFS done in ([\d.]+)s", ln)
        if m:
            phases["bfs"] = float(m.group(1))
        m = re.search(r"Inserted (\d+) rows in ([\d.]+)s", ln)
        if m:
            phases["insert"] = float(m.group(2))
        m = re.search(r"^\s+(reverse|ff_cones)\s+([\d.]+)s", ln)
        if m:
            phases[m.group(1)] = float(m.group(2))
        m = re.search(r"pad_ff ([\d.]+)s", ln)
        if m:
            phases["pad_ff"] = float(m.group(1))
    return wall, phases


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/bench_reach_sql.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db")
    ap.add_argument("--label")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    a = ap.parse_args()
    if a.compare:
        b, c = (json.loads(Path(p).read_text()) for p in a.compare)
        print(f"{'stage':14s} {'before s':>9s} {'after s':>9s} {'speedup':>8s}")
        for k in sorted(set(b["wall"]) | set(b["phases"]) | set(c["phases"])):
            x, y = b["wall"].get(k, b["phases"].get(k)), c["wall"].get(k, c["phases"].get(k))
            if x is None or y is None:
                continue
            print(f"{k:14s} {x:9.2f} {y:9.2f} {x / y if y else float('inf'):8.2f}x")
        bad = [t for t in TABLES if b["tables"][t] != c["tables"][t]]
        for t in TABLES:
            print(f"{t:18s} rows {b['tables'][t]['rows']:>9d} -> {c['tables'][t]['rows']:>9d}  "
                  f"hash {b['tables'][t]['sha256']} -> {c['tables'][t]['sha256']}  {'DIFF' if t in bad else 'identical'}")
        if bad:
            sys.exit(f"OUTPUT DIFFERS: {bad}")
        print("all output tables identical (rows + order-independent content hash)")
        return 0
    if not a.db or not a.label:
        ap.error("--db and --label (or --compare)")
    db_path = str(Path(a.db).resolve())
    if str(REPO / "databases") in db_path:
        sys.exit("refusing to run on a kept database; copy it first")
    env = dict(os.environ, PLURIBUS_SQLITE_PATH=db_path, PLURIBUS_DB_BACKEND="sqlite")
    conn = sqlite3.connect(db_path)
    bs_id = conn.execute("SELECT id FROM bitstreams WHERE label=?", (a.label,)).fetchone()[0]
    conn.close()
    res = {"tag": a.tag, "label": a.label, "db": db_path, "wall": {}, "phases": {}}
    # measured peaks (docs/rust-candidates.md): reach2 V02 2.1 GB, reach 0.35 GB; lease 3 GB (docs/memory-budget.md)
    with heavy_guard.lease(3, "bench_reach_sql", log):
        w, ph = run_stage("reach.py", ["--bitstream", a.label, "--workers", str(a.workers), "--replace"], env, "reach")
        res["wall"]["reach"] = w
        res["phases"].update({f"reach.{k}": v for k, v in ph.items()})
        w, ph = run_stage("reach2.py", ["--bitstream", a.label, "--workers", str(a.workers)], env, "reach2")
        res["wall"]["reach2"] = w
        res["phases"].update({f"reach2.{k}": v for k, v in ph.items()})
    res["tables"] = content_hash(db_path, bs_id)
    p = OUT / f"{a.tag}_{a.label}.json"
    p.write_text(json.dumps(res, indent=1))
    log.info("%s: walls %s phases %s -> %s", a.tag, {k: round(v, 2) for k, v in res["wall"].items()},
             {k: round(v, 2) for k, v in res["phases"].items()}, p)
    for t, v in res["tables"].items():
        log.info("  %-18s rows %9d  %s", t, v["rows"], v["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
