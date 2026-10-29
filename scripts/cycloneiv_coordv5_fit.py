#!/usr/bin/env python3.15t
"""Cyclone IV coordinate v5: sof - asm frame offset of the 12 non-LAB vendor bands (8 M9K + 4 MUL), fitted from set bits.  0 builds.

Per band b (old afx base A, width W): groups with >= 2 programmed entries, both inside [A, A + W); for every offset o the pair
(v, fa + o) of both entries must be set in a design's sof-indexed bitmap (cells via oracle idx_rbf).  A pair "hits" when the two cells
have the same set/clear vector over DESIGNS corpus designs and the vector is not constant (constant cells carry no signal).  The ladder value is 6173 - FX[plane column] - A (LAB: 6057 for the band at A = 58).
PREDICTION (before the run): the fitted offset equals the ladder value for each of the 12 bands (best hit count >= 3 x the
median over offsets); LAB calibration bands reproduce their ladder values.  REFUTED by any band whose best offset differs
from the ladder value or whose best count < 3 x median.
Needs the untracked vendor-analysis/altera/oracle/idx_rbf.npy.  Log tmp/logs/cycloneiv_coordv5_fit.log.  Peak RSS ~2 GB.
"""
import glob
import json
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_geom as cg  # noqa: E402

TMP = os.path.join(REPO, "tmp", "ddb")
IDX = os.path.join(REPO, "vendor-analysis", "altera", "oracle", "idx_rbf.npy")
log = logging.getLogger("coordv5_fit")
S, F, NP, NC, NV = 32, 796, 37, 6154, 6344
DESIGNS = 10
NGROUP = 2000                 # groups sampled per band
CH = 5_000_000
NONLAB = (233, 731, 1041, 1758, 2256, 2566, 3279, 3847, 4087, 4804, 5372, 5612)   # old afx bases of the 12 bands


def bitmaps(n):
    idx = np.load(IDX, mmap_mode="r")
    out = []
    for f in sorted(glob.glob(os.path.join(REPO, "corpus", "cycloneiv", "gx150_rb_0*", "bitstream.rbf"))):
        b = np.fromfile(f, np.uint8)
        if b.size != 4928127:
            continue
        U = b[S + NP * F: S + (NP + NC) * F].reshape(NC, F)
        Ub = np.unpackbits(U[:, 1:794, None], axis=2, bitorder="little")
        sof = np.zeros(NV * NC, np.uint8)
        for r0 in range(0, NC, 256):
            sof[np.asarray(idx[r0:r0 + 256, 1:794, :]).ravel()] = Ub[r0:r0 + 256].ravel()
        out.append(sof.reshape(NV, NC))
        if len(out) == n:
            break
    return out


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_coordv5_fit.log"), mode="w")])
    g = cg.load("ep4cgx150")
    afx = {int(k): v for k, v in json.load(open(os.path.join(TMP, "stingray4_dec_afx.json"))).items()}
    bases = np.array(sorted(set(afx.values())))
    nonlab_x = [x for x in sorted(g.kind) if g.kind[x] in ("M9K", "MUL")]
    pairing = dict(zip(NONLAB, nonlab_x))                                   # rank pairing: band order = plane column order
    cal = {93: 1, 198: 4, 1006: 20}                                           # LAB calibration bands -> plane column
    targets = {**{b: pairing[b] for b in NONLAB}, **cal}
    width = {b: (int(bases[np.searchsorted(bases, b) + 1]) - b if b in NONLAB else 18) for b in targets}
    pos = np.load(os.path.join(TMP, "stingray4_asm_pos.npy"), mmap_mode="r")
    pred = np.load(os.path.join(TMP, "stingray4_dec_pred.npy"), mmap_mode="r")
    gid = np.load(os.path.join(TMP, "stingray4_dec_gid.npy"), mmap_mode="r")
    lo = np.array(sorted(targets))
    hi = lo + np.array([width[b] for b in sorted(targets)])
    gs, vs, fs = [], [], []
    for a in range(0, len(pos), CH):
        p = np.asarray(pos[a:a + CH])
        fa = p % NC
        i = np.clip(np.searchsorted(lo, fa, "right") - 1, 0, len(lo) - 1)
        m = np.asarray(pred[a:a + CH]) & (fa >= lo[i]) & (fa < hi[i])
        gs.append(np.asarray(gid[a:a + CH])[m]); vs.append((p // NC)[m]); fs.append(fa[m])
    gs, vs, fs = np.concatenate(gs), np.concatenate(vs), np.concatenate(fs)
    first = np.r_[True, gs[1:] != gs[:-1]]
    st = np.flatnonzero(first)
    ok = np.r_[st[1:], len(gs)] - st >= 2
    e1, e2 = st[ok], st[ok] + 1
    band_of = lo[np.clip(np.searchsorted(lo, fs[e1], "right") - 1, 0, len(lo) - 1)]
    same = (fs[e2] >= band_of) & (fs[e2] < band_of + np.array([width[b] for b in band_of.tolist()]))
    log.info("groups with >= 2 programmed entries inside one target band: %d", int(same.sum()))
    maps = bitmaps(DESIGNS)
    log.info("designs read: %d", len(maps))
    A = np.stack(maps)
    del maps
    rng = np.random.default_rng(1)
    for b in sorted(targets):
        sel = np.flatnonzero(same & (band_of == b))
        if len(sel) == 0:
            log.info("band %d: no groups", b)
            continue
        sel = rng.choice(sel, min(NGROUP, len(sel)), replace=False)
        v1, f1, v2, f2 = vs[e1[sel]], fs[e1[sel]], vs[e2[sel]], fs[e2[sel]]
        o_lo, o_hi = -int(min(f1.min(), f2.min())), NC - int(max(f1.max(), f2.max()))
        offs = np.arange(o_lo, o_hi)
        cnt = np.zeros(len(offs), np.int64)
        for k, o in enumerate(offs.tolist()):
            a, c = A[:, v1, f1 + o], A[:, v2, f2 + o]
            cnt[k] = int(((a == c).all(0) & a.any(0) & ~a.all(0)).sum())
        top = np.argsort(-cnt)[:3]
        X = targets[b]
        ladder = 6173 - g.FX[X] - b
        lad_cnt = int(cnt[ladder - o_lo]) if o_lo <= ladder < o_hi else -1
        log.info("band %5d (plane X%-3d %s) groups %d: best o=%d (%d hits) 2nd %d (%d) 3rd %d (%d); median %d; ladder %d -> %d hits",
                 b, X, g.kind[X], len(sel), offs[top[0]], cnt[top[0]], offs[top[1]], cnt[top[1]], offs[top[2]], cnt[top[2]],
                 int(np.median(cnt)), ladder, lad_cnt)


if __name__ == "__main__":
    main()
