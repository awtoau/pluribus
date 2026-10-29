#!/usr/bin/env python3.15t
"""Cyclone IV coordinate v7 candidates vs the 399 forced LB -> R4 arcs, STRICT test.  0 builds.

Strict: exactly one R4 candidate of the source's fan-out has all its programmed group cells inside the raw diff, no shift.
Candidates (asm frame fa, asm v -> plane frame, plane v = 6344 - v):
  T1  plane = fa + 43                                       (LUT law, columns paired right-to-left; in-column order kept)
  T2  plane = 6190 - fa                                     (v6, sof2rbf reversal)
  T3  plane = FX[X'] - 18 + (fa - lo[X]),  X' = mirror column of X (column of fa by lo = FX - 61); column mirrored, in-column order kept
PREDICTION (coordinator, before the run): T1 or T3 >= 95 %.  REFUTED below 70 % for both.
Log tmp/logs/cycloneiv_coordv7_offline.log.
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_coordv2_validate as V  # noqa: E402

log = logging.getLogger("coordv7_offline")


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_coordv7_offline.log"), mode="w")])
    M = V.Model()
    g = M.g
    cols = [x for x in sorted(g.kind) if g.kind[x] in ("LAB", "M9K", "MUL")]
    lo = np.array([g.FX[x] - 61 for x in cols], np.int64)
    fxm = np.array([g.FX[cols[len(cols) - 1 - i]] for i in range(len(cols))], np.int64)
    log.info("columns %d", len(cols))

    def place(tag, fa):
        if tag == "T1":
            return fa + 43
        if tag == "T2":
            return 6190 - fa
        i = np.clip(np.searchsorted(lo, fa, "right") - 1, 0, len(lo) - 1)
        return fxm[i] - 18 + (fa - lo[i])

    z = np.load(os.path.join(REPO, "tmp", "ddb", "stingray4_rt_fanout.npz"))
    enum_r, idx_r = z["enum"][z["tpl"]], z["index"][z["tpl"]]
    le = np.flatnonzero(enum_r == 45)
    le_of = {(int(idx_r[r]), int(z["x"][r]), int(z["y"][r])): int(r) for r in le.tolist()}      # vendor x == fitter X
    A = V.arcs()
    for tag in ("T1", "T2", "T3"):
        per = collections.defaultdict(collections.Counter)
        nosrc = 0
        for r in A:
            on = set(r["on"])
            hits = 0
            s6 = le_of.get((r["lb"][3], r["lb"][1], r["lb"][2]))
            if s6 is None:
                nosrc += 1
                continue
            for k, d in M.r4_fan(s6):
                gi = int(M.gfirst[s6]) + k
                a, b = int(M.gstart[gi]), int(M.gstart[gi]) + int(M.gsize[gi])
                pos = np.asarray(M.pos[a:b])[np.asarray(M.pred[a:b])].astype(np.int64)
                fa, va = pos % 6154, pos // 6154
                cells = place(tag, fa) * V.PVMAX + (6344 - va)
                if len(cells) and all(int(c) in on for c in cells.tolist()):
                    hits += 1
            per[r["rel"]]["unique" if hits == 1 else ("none" if hits == 0 else "multi")] += 1
        tot = sum(sum(c.values()) for c in per.values()) + nosrc
        u = sum(c["unique"] for c in per.values())
        log.info("[%s] unique %d / %d = %.1f %%  by rel %s; no v6 source record %d", tag, u, tot, 100 * u / tot, {k: dict(v) for k, v in sorted(per.items())}, nosrc)


if __name__ == "__main__":
    main()
