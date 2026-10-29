#!/usr/bin/env python3.15t
"""Cyclone IV: sof frame - asm frame as a function of the asm frame alone, after the exact sof->rbf map incl. mirrored blocks (#165).  0 builds.
Diff cells (plane f = file frame 37 + r, plane v) -> (r, j, k) -> sof (sf, v) via the exact map (sof2rbf.py + mirror_mask.npy, unmodified).
Per arc: offsets d = sf - asm_frame with sof v == asm v for ALL group cells of the resolved record; used if exactly one d fits.
PREDICTION (before the run): sof frame - asm frame is single-valued per asm frame (one constant per 35-frame band) across the 379 arcs;
  the 125 plane-space frame collisions vanish.
REFUTED by: >= 5 % of asm frames with two or more sof offsets.
Log tmp/logs/cycloneiv_sofframe_test.log.
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "vendor-analysis", "altera", "scripts"))
import cycloneiv_coordv2_validate as V  # noqa: E402
import cycloneiv_fullpair_test as FP  # noqa: E402
import sof2rbf as S  # noqa: E402

log = logging.getLogger("sofframe")
PVMAX = V.PVMAX


def plane_to_sof(flat):
    """flat plane cells -> (sf, sv) with the exact (mirror-aware) inverse of sof2rbf.rbf_of_sof."""
    flat = np.asarray(flat, np.int64)
    f, v = flat // PVMAX, flat % PVMAX
    r = f - 37
    ok = (v >= 1) & (v <= 6344) & (r >= 0) & (r < 6154)
    k = 7 - (v - 1) // 793
    j = v - 793 * (7 - k)
    sv = 6344 - v
    sf = 6153 - r
    m = S.mirror_mask()[np.clip(j - 1, 0, 792), np.clip(k, 0, 7)]
    inmir = np.zeros(len(flat), bool)
    for b in S.BLOCKS:
        inb = ok & m & (r >= b) & (r <= b + 255)
        sf = np.where(inb, (6153 - b - 255) + (r - b), sf)
        inmir |= inb
    return sf, sv, inmir, ok


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_sofframe_test.log"), mode="w")])
    M = V.Model()
    A = V.arcs()
    used = []
    st = collections.Counter()
    for r in A:
        res = r.get("resolved")
        if not res:
            st["no_resolved"] += 1
            continue
        s = r["src"]
        fan = {d: k for k, d in M.r4_fan(s)}
        k = fan.get(res["rec"], res.get("k"))
        cells = FP.group_cells(M, s, k)
        sf, sv, inmir, ok = plane_to_sof(r["on"])
        bysv = collections.defaultdict(list)
        for a, b, m_ in zip(sf.tolist(), sv.tolist(), inmir.tolist()):
            bysv[b].append((a, m_))
        ds = None
        for fa, va in cells:
            c = {a - fa for a, _ in bysv.get(va, ())}
            ds = c if ds is None else ds & c
            if not ds:
                break
        ds = ds or set()
        st["unique" if len(ds) == 1 else ("nofit" if not ds else "ambig")] += 1
        if len(ds) == 1:
            d = next(iter(ds))
            mir = any(m_ for fa, va in cells for a, m_ in bysv[va] if a - fa == d)
            used.append((r, cells, d, mir))
    log.info("arcs: %s", dict(st))
    byf = collections.defaultdict(lambda: collections.defaultdict(list))
    for r, cells, d, mir in used:
        for fa, va in cells:
            byf[fa][d].append((M.src_col(r["src"]), r["rel"], va, mir))
    conf = {fa: dd for fa, dd in byf.items() if len(dd) > 1}
    log.info("asm frames %d; with >=2 sof offsets: %d = %.1f %%", len(byf), len(conf), 100 * len(conf) / max(len(byf), 1))
    nmir = sum(1 for r, c, d, m in used if m)
    log.info("used arcs touching a mirrored-block cell: %d of %d", nmir, len(used))
    for fa in sorted(conf)[:20]:
        log.info("  fa %d: %s", fa, {d: v[:3] for d, v in conf[fa].items()})
    log.info("collisions with a mirrored-block cell in any involved arc: %d", sum(1 for dd in conf.values() if any(x[3] for v in dd.values() for x in v)))
    bs = sorted(M.afx.values())
    import bisect
    bands = collections.defaultdict(collections.Counter)
    for fa, dd in byf.items():
        b = bs[max(bisect.bisect_right(bs, fa) - 1, 0)]
        for d, v in dd.items():
            bands[b][d] += len(v)
    log.info("per-band sof - asm offset (asm band start: offset:count)")
    for b in sorted(bands):
        log.info("  %5d: %s", b, dict(bands[b].most_common(3)))
    smp = os.path.join(REPO, "vendor-analysis", "altera", "oracle", "asm_vs_repo_sample.npy")
    if os.path.exists(smp):
        pp, sof = np.load(smp)
        fa_s, dd_s = pp % 6154, (sof % 6154) - pp % 6154
        cdec = {}
        for f in np.unique(fa_s):
            u, c = np.unique(dd_s[fa_s == f], return_counts=True)
            cdec[int(f)] = int(u[np.argmax(c)])
        dl = collections.defaultdict(collections.Counter)
        for r, cells, d, mir in used:
            for fa, va in cells:
                if fa in cdec:
                    dl[r["rel"]][d - cdec[fa]] += 1
        for rel in sorted(dl):
            log.info("arc offset - decompile offset, rel %+d: %s", rel, dict(dl[rel].most_common(6)))
    off0 = collections.Counter(d for r, c, d, m in used)
    log.info("top offsets overall: %s", off0.most_common(8))


if __name__ == "__main__":
    main()
