#!/usr/bin/env python3.15t
"""Pin usage statistics of an emitted Cyclone IV GX netlist: banks, sides, direction, DIFFIO pair runs, special pads.  Counts only (#168, #172).

  python3.15t scripts/cycloneiv_clean_pin_clusters.py NETLIST.v [--netlist-package F896] [--package F672] [--json OUT]
Input = `// IO pad_<ball> site ... dir=<dir>` comment lines of scripts/cycloneiv_clean_emit.py output (ball names of --netlist-package).
Each pad is mapped to its function (pad ddb: DIFFIO_<side><n><p|n>, CLKIO / DIFFCLK, PLL*_CLKOUT, ...) and to the ball of --package.
Log: tmp/logs/cycloneiv_clean_pin_clusters.log.  No design data is embedded; the netlist stays local.
"""
import argparse
import collections
import json
import logging
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
log = logging.getLogger("pin_clusters")
IO_LINE = re.compile(r"^// IO pad_(\w+) site \S+ dir=(\S+)")
DIFFIO = re.compile(r"DIFFIO_([TBLR])(\d+)([pn])")


def parse_io(text):
    """-> [(ball in the netlist's package, direction)] from the IO comment lines."""
    return [(m.group(1), m.group(2)) for m in map(IO_LINE.match, text.splitlines()) if m]


def pad_table(package):
    """-> {ball of `package`: {fn, balls: {pkg: ball}}} from the vendor package + pad ddb."""
    from lifters.cycloneiv_clean import pkgpad as K
    pads = K.pads()
    per = {c: K.pins(c) for c in (896, 672, 484)}
    by_pad = collections.defaultdict(dict)
    for c, pins in per.items():
        for i, j in K.pin_pad(pins).items():
            by_pad[j][f"F{c}"] = pins[i]["strs"][0]
    return {v[package]: {"fn": pads[j]["strs"][4], "balls": v} for j, v in by_pad.items() if package in v}


def runs(nums):
    """Maximal runs of consecutive integers -> [(first, last)]."""
    out = []
    for n in sorted(set(nums)):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return [tuple(r) for r in out]


def stats(ios, netlist_package="F896", package="F672"):
    """ios = [(ball, dir)].  -> dict of counts: direction, per side, pair coverage, runs of consecutive pair numbers, special pads."""
    tab = pad_table(netlist_package)
    dirs = collections.Counter(d for _, d in ios)
    side_dir = collections.defaultdict(collections.Counter)
    pairs = collections.defaultdict(lambda: collections.defaultdict(dict))      # side -> number -> {p|n: dir}
    special = []
    unbonded = 0
    for ball, d in ios:
        row = tab.get(ball)
        if row is None:
            raise SystemExit(f"ball {ball} not in the {netlist_package} pad table")
        if package not in row["balls"]:
            unbonded += 1
        m = DIFFIO.match(row["fn"])
        if m:
            side, n, pn = m.group(1), int(m.group(2)), m.group(3)
            side_dir[side][d] += 1
            pairs[side][n][pn] = d
        else:
            special.append((row["fn"], d))
    out = {"pads": len(ios), "direction": dict(dirs), "unbonded_in_package": unbonded, "sides": {}, "special": dict(collections.Counter(f for f, _ in special))}
    both = 0
    for side in sorted(pairs):
        nums = sorted(pairs[side])
        b = sum(1 for n in nums if len(pairs[side][n]) == 2)
        both += b
        out["sides"][side] = {"direction": dict(side_dir[side]), "pairs_touched": len(nums), "pairs_both_p_n": b,
                              "runs": [(a, z) for a, z in runs(nums)], "longest_run": max((z - a + 1 for a, z in runs(nums)), default=0)}
    out["pairs_touched"] = sum(s["pairs_touched"] for s in out["sides"].values())
    out["pairs_both_p_n"] = both
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("netlist")
    ap.add_argument("--netlist-package", default="F896", choices=["F896", "F672", "F484"])
    ap.add_argument("--package", default="F672", choices=["F896", "F672", "F484"])
    ap.add_argument("--json")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_pin_clusters.log"), "w")])
    ios = parse_io(open(a.netlist).read())
    res = stats(ios, a.netlist_package, a.package)
    log.info(json.dumps(res, indent=1, default=list))
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1, default=list)


if __name__ == "__main__":
    main()
