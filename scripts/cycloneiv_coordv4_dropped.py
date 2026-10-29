#!/usr/bin/env python3.15t
"""Cyclone IV coordinate v3: what do the entries dropped by the relabelled band rule feed?  Read-only, 0 builds.

Entries with pf == DROP_F under v3 (stingray4_decv3_pf.npy) and a real pf under the old placement (stingray4_dec_pf.npy):
counts by old plane column kind, by source-record enum, by asm frame; plus the asm frames (distinct) involved.
Also: how many v3 entries land in the 8 mirrored M9K blocks (vendor-analysis sof2rbf.BLOCKS): the mirror mask only acts there.
Log tmp/logs/cycloneiv_coordv4_dropped.log.
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "vendor-analysis", "altera", "scripts"))
import cycloneiv_geom as cg  # noqa: E402

TMP = os.path.join(REPO, "tmp", "ddb")
log = logging.getLogger("coordv4_dropped")
DROP_F = 30000
CH = 5_000_000
ENUM_NAME = {268: "R4", 275: "C4", 273: "R24", 281: "C16", 282: "LI", 45: "LE_BUFFER"}


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_coordv4_dropped.log"), mode="w")])
    g = cg.load("ep4cgx150")
    xs = sorted(g.FX, key=lambda x: g.FX[x])
    fxs = np.array([g.FX[x] for x in xs], np.int64)
    z = np.load(os.path.join(TMP, "stingray4_rt_fanout.npz"))
    enum_rec = z["enum"][z["tpl"]]
    pos = np.load(os.path.join(TMP, "stingray4_asm_pos.npy"), mmap_mode="r")
    pf0 = np.load(os.path.join(TMP, "stingray4_dec_pf.npy"), mmap_mode="r")
    pf3 = np.load(os.path.join(TMP, "stingray4_decv3_pf.npy"), mmap_mode="r")
    PV = np.load(os.path.join(TMP, "stingray4_decv3_pv.npy"), mmap_mode="r")
    gid = np.load(os.path.join(TMP, "stingray4_decv3_gid.npy"), mmap_mode="r")
    grec = np.load(os.path.join(TMP, "stingray4_decv3_grec.npy"), mmap_mode="r")
    by_kind, by_enum, frames, n_gain = collections.Counter(), collections.Counter(), collections.Counter(), 0
    try:
        import sof2rbf as S
        blocks = S.BLOCKS
    except Exception as e:                                   # vendor-analysis/ is untracked; blocks are informational here
        log.info("sof2rbf not importable (%s); mirrored-block count skipped", e)
        blocks = ()
    in_blk = changed = 0
    afx = {int(k): v for k, v in __import__("json").load(open(os.path.join(TMP, "stingray4_dec_afx.json"))).items()}
    lab_bases = np.array(sorted(afx.values()))
    lost_lab = collections.Counter()
    for a in range(0, len(pf0), CH):
        p0, p3 = np.asarray(pf0[a:a + CH]), np.asarray(pf3[a:a + CH])
        lost = (p3 == DROP_F) & (p0 != DROP_F)
        n_gain += int(((p3 != DROP_F) & (p0 == DROP_F)).sum())
        for b in blocks:
            in_blk += int((((p3.astype(np.int64) - 37) >= b) & ((p3.astype(np.int64) - 37) <= b + 255) & (p3 != DROP_F)).sum())
        if blocks:           # exact sof -> rbf map (mirror mask) applied to the v3 placement: entries that would move
            f3, pv3 = p3.astype(np.int64), np.asarray(PV[a:a + CH]).astype(np.int64)
            ok = (f3 >= 37) & (f3 < 37 + 6154) & (pv3 >= 1) & (pv3 <= 6344)
            r_new, _j, _k = S.rbf_of_sof(((6344 - pv3) * 6154 + (6153 - (f3 - 37)))[ok])
            changed += int((r_new != (f3 - 37)[ok]).sum())
        if not lost.any():
            continue
        e = np.flatnonzero(lost)
        col = np.array(xs)[np.clip(np.searchsorted(fxs, p0[e].astype(np.int64), "right") - 1, 0, len(xs) - 1)]
        for c, n in zip(*np.unique(col, return_counts=True)):
            by_kind[g.kind[int(c)]] += int(n)
        en = enum_rec[np.asarray(grec[np.asarray(gid[a:a + CH])[e]])]
        for c, n in zip(*np.unique(en, return_counts=True)):
            by_enum[ENUM_NAME.get(int(c), int(c))] += int(n)
        for f, n in zip(*np.unique(np.asarray(pos[a:a + CH])[e] % 6154, return_counts=True)):
            frames[int(f)] += int(n)
            lost_lab[int(lab_bases[np.searchsorted(lab_bases, f, "right") - 1])] += int(n)
    log.info("entries lost (real pf -> DROP) by old plane column kind: %s", dict(by_kind))
    log.info("by source record enum: %s", dict(by_enum))
    log.info("distinct asm frames among lost entries: %d; entries lost %d; entries gained (DROP -> real): %d", len(frames), sum(frames.values()), n_gain)
    log.info("asm band bases (old afx values) holding the lost entries: %d bands %s", len(lost_lab), sorted(lost_lab))
    log.info("v3 entries moved by the exact sof->rbf map incl. mirror mask: %d", changed)
    log.info("v3 entries inside the 8 mirrored M9K blocks (mask acts only there): %d", in_blk)


if __name__ == "__main__":
    main()
