#!/usr/bin/env python3.15t
"""Count how often each gkey() rule fires while lifting a bitstream.

Per bitstream: decode (native), parse_config + recover_netlist with gkey()
wrapped; each call classified by machxo2_oracle_compare.Ctx.gkey_branch().
Reports calls and distinct (row, col, name) per branch.

Usage: python3.15t scripts/machxo2_gkey_hits.py --out tmp/gkey_hits.json LABEL=path.bin ...
Log:   tmp/logs/machxo2_gkey_hits.log
"""
import argparse
import json
import os
import sys
from collections import Counter

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
import machxo2_oracle_compare as MC  # noqa: E402

MC.LOG_PATH = os.path.join(MC.REPO, "tmp", "logs", "machxo2_gkey_hits.log")


def hits(binpath, workdir, label):
    C = MC.ctx()
    L = C.L
    text, _pb, _bram = MC.native_config.config_from_file(
        binpath, device=MC.DEVICE, db_root=os.environ["TRELLIS_DBROOT"])
    cfg = os.path.join(workdir, f"{label}.config")
    with open(cfg, "w") as fh:
        fh.write(text)
    calls, distinct = Counter(), {}
    orig = L.gkey

    def wrapped(row, col, name):
        br = C.gkey_branch(row, col, name)
        calls[br] += 1
        distinct.setdefault(br, set()).add((row, col, name))
        return orig(row, col, name)

    L.gkey = wrapped
    try:
        pc = L.parse_config(cfg)
        L.recover_netlist(pc)
    finally:
        L.gkey = orig
    return {"calls": dict(calls), "distinct": {k: len(v) for k, v in distinct.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", default=os.path.join(MC.REPO, "tmp", "gkey_hits"))
    ap.add_argument("bitstreams", nargs="+", help="LABEL=path.bin")
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    os.makedirs(os.path.dirname(MC.LOG_PATH), exist_ok=True)
    res = {}
    for spec in a.bitstreams:
        label, path = spec.split("=", 1)
        res[label] = hits(path, a.workdir, label)
        MC.log(f"[hits] {label}: {res[label]}")
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    branches = sorted({b for r in res.values() for b in r["calls"]})
    print("branch".ljust(30) + "".join(f"{l:>22}" for l in res))
    for b in branches:
        print(b.ljust(30) + "".join(
            f"{res[l]['calls'].get(b, 0):>10} / {res[l]['distinct'].get(b, 0):<9}"
            for l in res))
    print("(calls / distinct tile-wire)")


if __name__ == "__main__":
    main()
