#!/usr/bin/env python3.15t
"""Cyclone IV coordinate v3 (F1 relabel only): do the double-offset asm frames collapse?  Read-only, 0 builds.

Per asm frame, offset = sof frame - asm frame, with sof from the plane placement (plane -> rbf index via the oracle
idx_rbf, same sample as vendor-analysis/altera/scripts/asm_vs_repo_plane.py: seed 1, 400,000 entries).
PREDICTION (before the run): the 88 asm frames with two offsets under the old placement have one offset each under
the relabelled placement (decv3 pf).  REFUTED by any of the 88 keeping two offsets, or new double-offset frames.
Log tmp/logs/cycloneiv_coordv3_collapse.log.
"""
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(REPO, "tmp", "ddb")
IDX = os.path.join(REPO, "vendor-analysis", "altera", "oracle", "idx_rbf.npy")
log = logging.getLogger("coordv3_collapse")
NSAMPLE = 400000


def offsets(pos, pf, pv, idx, sel):
    p = np.asarray(pos[sel])
    f, v = np.asarray(pf[sel]).astype(np.int64), np.asarray(pv[sel]).astype(np.int64)
    k = 7 - (v - 1) // 793
    j = v - 793 * (7 - k)
    ok = (v >= 1) & (v <= 6344) & (f >= 37) & (f < 37 + 6154)
    sof = np.full(len(p), -1, np.int64)
    sof[ok] = idx[(f - 37)[ok], j[ok], k[ok]]
    good = ok & (sof >= 0) & (sof < 39040976)
    fa = p % 6154
    return fa[good], (sof[good] % 6154) - fa[good], good


def multi(fa, d):
    key = np.unique(np.stack([fa, d], 1), axis=0)
    u, c = np.unique(key[:, 0], return_counts=True)
    return set(u[c > 1].tolist()), len(u), set(u.tolist())


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_coordv3_collapse.log"), mode="w")])
    pos = np.load(os.path.join(TMP, "stingray4_asm_pos.npy"), mmap_mode="r")
    idx = np.load(IDX, mmap_mode="r")
    sel = np.sort(np.random.default_rng(1).choice(len(pos), NSAMPLE, replace=False))
    res = {}
    for tag, pre in (("old", "stingray4_dec"), ("v3", "stingray4_decv3")):
        pf = np.load(os.path.join(TMP, f"{pre}_pf.npy"), mmap_mode="r")
        pv = np.load(os.path.join(TMP, f"{pre}_pv.npy"), mmap_mode="r")
        fa, d, good = offsets(pos, pf, pv, idx, sel)
        m, n, allf = multi(fa, d)
        res[tag] = (m, n, allf)
        log.info("[%s] usable %d, asm frames %d, frames with >1 offset: %d", tag, int(good.sum()), n, len(m))
    mo, mn = res["old"][0], res["v3"][0]
    log.info("old double frames still present (usable) under v3: %d of %d; asm frames lost under v3: %d", len(mo & res["v3"][2]), len(mo), len(res["old"][2] - res["v3"][2]))
    log.info("old double-offset frames now single or unusable: %d of %d; still double: %d; new double (not in old): %d",
             len(mo - mn), len(mo), len(mo & mn), len(mn - mo))


if __name__ == "__main__":
    main()
