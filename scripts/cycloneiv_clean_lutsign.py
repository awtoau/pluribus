#!/usr/bin/env python3.15t
"""LAB LUT address hypotheses scored against the Quartus-built LUT specimens (#165).  Replaces the geometry-JSON one-cell fit.
Needs vendor-analysis/ (asmdb body, blkrba csv) and tmp/cycloneiv_clean/lut_specimens/observed.npz (cycloneiv_clean_lut_specimens.py).
Per (column pairing, row pairing, sx, sy): frame / v constants = mode over all specimen cells, sites whose 16 cells match as a set.
Log: tmp/logs/cycloneiv_clean_lutsign.log"""
import itertools
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests", "cycloneiv_clean"))
import o1_model as M  # noqa: E402
from lifters.cycloneiv_clean import plane as P  # noqa: E402


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    out = open(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_lutsign.log"), "w")

    def log(s):
        print(s)
        out.write(s + "\n")
    t = P.load_tables()
    hi0, lo = M.instance_cells()
    dx, dy = M.blkrba()
    xs, _ = M.lab_columns()
    o = M.observed()
    oc = M.site_cells(o)
    rank = np.array([xs.index(x) for x in o["sx"]])
    for colp, rowp, sx, sy in itertools.product(["ltr", "rtl"], ["asc", "desc"], [1, -1], [1, -1]):
        c = rank if colp == "ltr" else M.COLS - 1 - rank
        r = (o["sy"] - 1) if rowp == "asc" else M.ROWS_ - o["sy"]
        pred = M.predicted_sof(c, r, o["le"], hi0, lo, dx, dy, sx, sy)
        cs, cv, votes = M.fit_constants(pred, oc)
        pc = M.predicted_cells(pred, cs, cv, t)
        ok = M.site_matches(pc, oc)
        perm = M.bit_permutations(pc, oc)
        pins = sum(M.is_index_bit_permutation(p) for p in perm)
        pins_c = sum(M.is_index_bit_permutation(15 - p) for p in perm)
        log(f"{colp} {rowp} sx {sx:+d} sy {sy:+d} frame_const {cs} v_const {cv} votes {votes} sites_ok {int(ok.sum())}/{len(ok)} "
            f"bitorder=pin_swap {pins} bitorder=15-pin_swap {pins_c}")


if __name__ == "__main__":
    main()
