#!/usr/bin/env python3.15t
"""Cyclone IV coordinate v6 offline: do the raw-diff cells of the forced LB -> R4 arcs land on records at the source / destination tile?  0 builds.

Uses the prepared v6 arrays (PLURIBUS_COORD_V2=6 prepare: plane cell = sof2rbf(raw address)); diff cells 'on' of
tmp/hop_specimens/results_r4*.json looked up in (pf * 6368 + pv); owner record of an entry = stingray4_asm_rec; vendor x = fitter X.
PREDICTION (audit): >= 95 % of arcs have a record with >= 2 flipped cells at the source tile AND one at the destination tile.
Log tmp/logs/cycloneiv_coordv6_arcs.log.
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_coordv2_validate as V  # noqa: E402

TMP = os.path.join(REPO, "tmp", "ddb")
log = logging.getLogger("coordv6_arcs")


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_coordv6_arcs.log"), mode="w")])
    z = np.load(os.path.join(TMP, "stingray4_rt_fanout.npz"))
    vx, vy = z["x"], z["y"]
    A = V.arcs()
    q = {}
    for ai, r in enumerate(A):
        for c in r["on"]:
            q.setdefault(int(c), []).append(ai)
    qa = np.array(sorted(q), np.int64)
    pf = np.load(os.path.join(TMP, "stingray4_decv6_pf.npy"), mmap_mode="r")
    pv = np.load(os.path.join(TMP, "stingray4_decv6_pv.npy"), mmap_mode="r")
    rec = np.load(os.path.join(TMP, "stingray4_asm_rec.npy"), mmap_mode="r")
    hit = collections.defaultdict(list)
    for a in range(0, len(pf), 5_000_000):
        flat = np.asarray(pf[a:a + 5_000_000]).astype(np.int64) * 6368 + np.asarray(pv[a:a + 5_000_000])
        for i in np.flatnonzero(np.isin(flat, qa)).tolist():
            hit[int(flat[i])].append(int(rec[a + i]))
    res = collections.Counter()
    per_rel = collections.defaultdict(collections.Counter)
    for ai, r in enumerate(A):
        owners = collections.Counter(rc for c in r["on"] for rc in hit.get(int(c), ()))
        sX, sY = r["lb"][1], r["lb"][2]
        dX, dY = r["tile"]
        s_ok = any(n >= 2 and vx[rc] == sX and vy[rc] == sY for rc, n in owners.items())
        d_ok = any(n >= 2 and vx[rc] == dX and vy[rc] == dY for rc, n in owners.items())
        res[(s_ok, d_ok)] += 1
        per_rel[r["rel"]][(s_ok, d_ok)] += 1
    n = len(A)
    log.info("arcs %d: (source tile hit, destination tile hit) %s", n, dict(res))
    log.info("source tile hit %.1f %%, destination tile hit %.1f %%", 100 * (res[(True, True)] + res[(True, False)]) / n,
             100 * (res[(True, True)] + res[(False, True)]) / n)
    for rel in sorted(per_rel):
        log.info("rel %+d: %s", rel, dict(per_rel[rel]))


if __name__ == "__main__":
    main()
