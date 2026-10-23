#!/usr/bin/env python3.15t
"""Cyclone V lifter scorecard: lifted netlist vs the Quartus post-fit oracle, whole corpus.

Runs scripts/cyclonev_postfit_compare.py one design at a time (never parallel: 8
concurrent 85F-class lifts hit ~30 GB, #111), then aggregates postfit_compare.
Per field: matched / (matched + missing + extra + wrong), plus the raw fault counts.
  matched = MATCH   missing = LIFT_MISSING   extra = LIFT_ONLY
  wrong   = MISMATCH + UNMODELLED
No headline ever hides missing/extra (CLAUDE.md "Scoring faults").

Usage: PLURIBUS_SQLITE_PATH=<corpus db copy> python3.15t scripts/cyclonev_lift_scorecard.py --label NAME [--score-only]
Log: tmp/logs/cyclonev_lift_scorecard.log ; table: tmp/scorecard-NAME.json
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "tmp" / "logs" / "cyclonev_lift_scorecard.log"
# Stall guard: a design prints its summary only at the end, so the limit is per design.
# Baseline cold worst case measured on this box (see tmp/scorecard-*.json "max_design_s");
# overall = 3x that (host-process backstop, awto-dan#53).
PER_DESIGN_LIMIT_S = int(os.environ.get("SCORECARD_DESIGN_LIMIT_S", "300"))

FAMILIES = [
    ("lut function", ["lut_mask", "lut_mask_arith", "lut.extra"]),
    ("lut inputs", ["conn.dataa", "conn.datab", "conn.datac", "conn.datad", "conn.datae",
                    "conn.dataf", "conn_arith.dataa", "conn_arith.datab", "conn_arith.datac",
                    "conn_arith.datad", "conn_arith.datae", "conn_arith.dataf"]),
    ("ff.present", ["ff.present", "ff.extra"]),
    ("ff.d", ["ff.d"]), ("ff.clk", ["ff.clk"]), ("ff.clrn", ["ff.clrn"]),
    ("ff.ena", ["ff.ena"]), ("ff.sclr", ["ff.sclr"]), ("ff.sload", ["ff.sload"]),
    ("pins", ["pin"]),
    ("obuf.i", ["conn.obuf.i"]),
]


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def run_designs(designs):
    times = {}
    env = dict(os.environ)
    for i, d in enumerate(designs, 1):
        t0 = time.time()
        try:
            r = subprocess.run(["python3.15t", str(REPO / "scripts" / "cyclonev_postfit_compare.py"), d],
                               env=env, capture_output=True, text=True, timeout=PER_DESIGN_LIMIT_S)
        except subprocess.TimeoutExpired:
            log(f"TIMEOUT {d}: compare exceeded {PER_DESIGN_LIMIT_S}s (expected < 60s) -- skipped")
            times[d] = None
            continue
        dt = time.time() - t0
        times[d] = dt
        if r.returncode != 0:
            log(f"FAIL {d} rc={r.returncode} after {dt:.1f}s: {r.stderr.strip().splitlines()[-1:]}")
        elif i % 20 == 0 or dt > 30:
            log(f"[{i}/{len(designs)}] {d} {dt:.1f}s")
    return times


def aggregate(designs):
    import sqlite3
    db = os.environ["PLURIBUS_SQLITE_PATH"]
    c = sqlite3.connect(db)
    cnt = collections.defaultdict(collections.Counter)
    ph = ",".join("?" * len(designs))
    for field, verdict, n in c.execute(
            "select p.field, p.verdict, count(*) from postfit_compare p join postfit_builds b on p.build=b.id "
            f"where b.design in ({ph}) group by 1,2", designs):
        cnt[field][verdict] += n
    out = {}
    for name, fields in FAMILIES:
        t = collections.Counter()
        for f in fields:
            t.update(cnt.get(f, {}))
        wrong = t["MISMATCH"] + t["UNMODELLED"]
        total = t["MATCH"] + t["LIFT_MISSING"] + t["LIFT_ONLY"] + wrong
        out[name] = dict(matched=t["MATCH"], missing=t["LIFT_MISSING"], extra=t["LIFT_ONLY"],
                         wrong=wrong, total=total, faults=total - t["MATCH"],
                         pct=round(100.0 * t["MATCH"] / total, 1) if total else None)
    return out, len(designs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--lifter-file", help="score this lifter file instead of lifters/cyclonev_lift.py")
    ap.add_argument("--score-only", action="store_true", help="aggregate the existing postfit_compare")
    a = ap.parse_args()
    if "PLURIBUS_SQLITE_PATH" not in os.environ:
        sys.exit("set PLURIBUS_SQLITE_PATH to the corpus DB copy (never the live one)")
    times = {}
    designs = sorted(p.parent.name for p in (REPO / "corpus" / "cyclonev").glob("*/decomp.bt"))
    if not a.score_only:
        log(f"=== {a.label}: {len(designs)} designs with decomp.bt")
        if a.lifter_file:
            os.environ["CYCLONEV_LIFTER_FILE"] = str(Path(a.lifter_file).resolve())
        times = run_designs(designs)
    out, n_builds = aggregate(designs)
    ok_times = [t for t in times.values() if t]
    res = dict(label=a.label, builds=n_builds, max_design_s=max(ok_times) if ok_times else None,
               total_s=sum(ok_times), fields=out)
    (REPO / "tmp" / f"scorecard-{a.label}.json").write_text(json.dumps(res, indent=1))
    log(f"--- {a.label}: {n_builds} builds, max design {res['max_design_s']}, total {res['total_s']:.0f}s")
    log(f"{'field':14s} {'matched':>8s} {'missing':>8s} {'extra':>6s} {'wrong':>6s} {'total':>7s} {'%':>6s} {'faults':>7s}")
    for name, v in out.items():
        log(f"{name:14s} {v['matched']:8d} {v['missing']:8d} {v['extra']:6d} {v['wrong']:6d} "
            f"{v['total']:7d} {v['pct'] if v['pct'] is not None else '-':>6} {v['faults']:7d}")


if __name__ == "__main__":
    main()
