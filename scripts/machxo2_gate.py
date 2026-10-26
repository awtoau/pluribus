#!/usr/bin/env python3.15t
"""Run the MachXO2 Diamond-oracle comparison over every corpus set, serially, and print one headline.

    python3.15t scripts/machxo2_gate.py --tag base [--workers 4] [--sets old constructs coverage globals]
    python3.15t scripts/machxo2_gate.py --diff base after

Sets: old = diamond-fuzz (2779), constructs, coverage, globals (multi-clock / secondary-control designs).
Per-set summaries land in tmp/ocmp/<tag>/<set>.json. Headline counts every non-MATCH as a fault.
Each set is one machxo2_oracle_compare.py run (it holds the heavy lock and the RAM gate itself).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = {
    "old": ("diamond-fuzz/targets", "corpus/machxo2/diamond-fuzz"),
    "constructs": ("corpus/machxo2/constructs",) * 2,
    "coverage": ("corpus/machxo2/coverage",) * 2,
    "globals": ("corpus/machxo2/globals",) * 2,
}


def _field(s, name):
    r = {}
    for k, v in s["site_field_verdicts"].items():
        if k.startswith(name + ":"):
            r[k.split(":")[1]] = v
    return r


def headline(s):
    pips, nets = s["pips"], s["net_verdicts"]
    out = {"pips": (pips.get("MATCH", 0), sum(pips.values())),
           "nets": (nets.get("MATCH", 0), sum(nets.values()))}
    for key, fld in (("reg_clock", "FF#.lift.clk"), ("reg_ce", "FF#.lift.ce"),
                     ("reg_lsr", "FF#.lift.lsr"), ("reg_d", "FF#.lift.d")):
        f = _field(s, fld)
        out[key] = (f.get("MATCH", 0), sum(f.values()))
    return out


def load(tag):
    d = os.path.join(REPO, "tmp", "ocmp", tag)
    return {n: json.load(open(os.path.join(d, n + ".json")))
            for n in DIRS if os.path.exists(os.path.join(d, n + ".json"))}


def show(tag):
    S = load(tag)
    tot = {}
    print(f"== {tag}")
    for n, s in S.items():
        h = headline(s)
        print(f"  {n:11s} failed={len(s['failed'])} " + "  ".join(f"{k} {a}/{b}" for k, (a, b) in h.items()))
        for k, (a, b) in h.items():
            t = tot.setdefault(k, [0, 0])
            t[0] += a
            t[1] += b
    print("  ALL         " + "  ".join(f"{k} {a}/{b} = {100.0 * a / b if b else 0:.2f}%"
                                      for k, (a, b) in tot.items()))
    return S


def diff(a, b):
    A, B = load(a), load(b)
    for n in A:
        if n not in B:
            continue
        for sec in ("pips", "net_verdicts", "site_field_verdicts", "gkey_verdicts"):
            ka, kb = A[n][sec], B[n][sec]
            for k in sorted(set(ka) | set(kb)):
                if ka.get(k, 0) != kb.get(k, 0):
                    print(f"  {n:11s} {sec}.{k}: {ka.get(k, 0)} -> {kb.get(k, 0)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sets", nargs="*", default=list(DIRS))
    ap.add_argument("--old-targets", help="dir holding the old fuzz targets' impl1/*.bit (untracked; "
                    "a worktree lacks them: point at the main checkout)")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"))
    a = ap.parse_args()
    if a.diff:
        show(a.diff[0])
        show(a.diff[1])
        diff(*a.diff)
        return 0
    od = os.path.join(REPO, "tmp", "ocmp", a.tag)
    os.makedirs(od, exist_ok=True)
    for n in a.sets:
        tdir, out = DIRS[n]
        if n == "old" and a.old_targets:
            tdir = a.old_targets
        cmd = [sys.executable, os.path.join(REPO, "scripts", "machxo2_oracle_compare.py"),
               "--targets-dir", os.path.join(REPO, tdir), "--out", os.path.join(REPO, out),
               "--workers", str(a.workers)]
        with open(os.path.join(od, n + ".log"), "w") as fh:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT).returncode
        if rc:
            print(f"compare {n} exit {rc}; see {od}/{n}.log")
            return 1
        shutil.copy(os.path.join(REPO, out, "_compare_summary.json"), os.path.join(od, n + ".json"))
    show(a.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
