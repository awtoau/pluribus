#!/usr/bin/env python3.15t
"""Cyclone IV coordinate v6 (identity: raw asm address = sof bit index, then sof2rbf) vs the 399 forced LB -> R4 arcs.  0 builds.

v6 plane cell of an asm entry: (r, j, k) = rbf_of_sof(raw address), frame = 37 + r, v = 793 * (7 - k) + j.  No afx, bands, source terms.
PREDICTION (before the run): >= 70 % of the rel -1 / +3 arcs (and rel 0 / +4) have exactly one R4 candidate record whose
programmed group cells all lie inside the raw diff.  REFUTED below 70 % of rel -1/+3 arcs.
On failure: distribution of (F3 plane frame - v6 plane frame) per arc over the arcs F3 reproduces (383), by source column and rel.
Needs untracked vendor-analysis/altera/scripts/sof2rbf.py.  Log tmp/logs/cycloneiv_coordv6_validate.log.
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
import sof2rbf as S  # noqa: E402

log = logging.getLogger("coordv6_validate")


def v6_cells(M, s, k):
    gi = int(M.gfirst[s]) + k
    a, b = int(M.gstart[gi]), int(M.gstart[gi]) + int(M.gsize[gi])
    pos = np.asarray(M.pos[a:b])[np.asarray(M.pred[a:b])].astype(np.int64)
    r, j, kk = S.rbf_of_sof(pos)
    return (37 + r) * V.PVMAX + 793 * (7 - kk) + j, 37 + r


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_coordv6_validate.log"), mode="w")])
    M = V.Model()
    A = V.arcs()
    per = collections.defaultdict(collections.Counter)
    delta = collections.defaultdict(collections.Counter)
    for r in A:
        on = set(r["on"])
        hits = [(k, d) for k, d in M.r4_fan(r["src"]) if all(int(x) in on for x in v6_cells(M, r["src"], k)[0].tolist())]
        per[r["rel"]]["unique" if len(hits) == 1 else ("none" if not hits else "multi")] += 1
        Xs, h3 = V.classify(M, r)
        if len(h3) == 1:
            k, d = h3[0]
            f3 = np.asarray(M.cells(r["src"], k, Xs)) // V.PVMAX
            f6 = v6_cells(M, r["src"], k)[1]
            delta[(r["rel"],)][tuple(np.unique(f3 - f6).tolist())[:1] or (None,)] += 1
            delta[("X", Xs)][int(np.median(f3 - f6))] += 1
    for rel in sorted(per):
        n = sum(per[rel].values())
        log.info("rel %+d: %s  (%.1f %% unique)", rel, dict(per[rel]), 100 * per[rel]["unique"] / n)
    m13 = sum(per[r]["unique"] for r in (-1, 3)) / sum(sum(per[r].values()) for r in (-1, 3))
    log.info("rel -1/+3 reproduced: %.1f %%", 100 * m13)
    ds = collections.Counter()
    for k, c in delta.items():
        if k[0] == "X":
            ds.update({v: n for v, n in c.items()})
    log.info("(F3 frame - v6 frame) per arc, median over cells: %d distinct values over %d arcs; examples %s",
             len(ds), sum(ds.values()), ds.most_common(8))
    xs = {k[1]: dict(c) for k, c in sorted(delta.items(), key=str) if k[0] == "X"}
    log.info("by source column (first 12): %s", dict(list(xs.items())[:12]))


if __name__ == "__main__":
    main()
