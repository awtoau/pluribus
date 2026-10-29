#!/usr/bin/env python3.15t
"""Cyclone IV: which SOURCE element carries each R4 arc's group, destination record fixed? (#165)  0 builds.
Destination = the table's resolved record. Sources = every record s' within vx +-4, vy +-2 of the assumed source whose fan-out holds it (stingray4_rt_fanout.npz); group = dest's position in s' fan-out. Frame offsets fixed to the decompile table (nearest-band rule
  for absent frames), zero free shift; fit = all group cells in the arc's raw diff (sof space, exact map), v exact.
PREDICTION (before the run): >= 95 % of rel 0 / +4 arcs get exactly one fitting source, one column pitch (vx +-1) from the assumed LE_BUFFER;
  rel -1 / +3 controls keep the assumed source.
REFUTED by: < 90 % unique, or the found sources not at vx +-1.
Log tmp/logs/cycloneiv_srcsearch_test.log.
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
import cycloneiv_recsearch_test as RS  # noqa: E402
import cycloneiv_sofframe_test as SF  # noqa: E402

log = logging.getLogger("srcsearch")


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_srcsearch_test.log"), mode="w")])
    M = V.Model()
    D = M.D
    keys, offv = RS.offsets()
    cache = {}

    def off(fa):
        if fa not in cache:
            cache[fa] = int(offv[np.argmin(np.abs(keys - fa))])
        return cache[fa]

    tpl = np.asarray(D.tpl)
    vxa, vya = np.asarray(M.vx), np.asarray(M.vy)

    def sources_of(d, s0):
        """candidate sources: any record within vx +-4, vy +-2 of the assumed one whose fan-out holds d (inversion restricted to the neighbourhood)."""
        cand = np.flatnonzero((np.abs(vxa - vxa[s0]) <= 4) & (np.abs(vya - vya[s0]) <= 2))
        out = []
        for c in cand.tolist():
            f = D.fan_of(c)
            w = np.flatnonzero(f == d)
            for k in w.tolist():
                out.append((c, k))
        return out

    per = collections.defaultdict(collections.Counter)
    rel_tab = collections.defaultdict(collections.Counter)
    ex = []
    for r in V.arcs():
        res = r.get("resolved")
        if not res:
            continue
        rel, s0, d = r["rel"], r["src"], res["rec"]
        sf, sv, _, ok = SF.plane_to_sof(r["on"])
        diff = set(zip(sf.tolist(), sv.tolist()))
        hits = []
        for s, k in sources_of(d, s0):
            ng = int(M.gsize[int(M.gfirst[s]) + k]) if int(M.gfirst[s]) + k < len(M.gsize) else 0
            if not ng:
                continue
            cells = FP.group_cells(M, s, k)
            if cells and len(cells) >= 2 and all((fa + off(fa), va) in diff for fa, va in cells):
                hits.append((s, k))
        c = "unique" if len(hits) == 1 else ("none" if not hits else "multi")
        per[rel][c] += 1
        for s, k in hits:
            t0, t1 = tpl[s0], tpl[s]
            rel_tab[rel][("same" if s == s0 else "other", "enum%d" % M.enum_t[t1], "dvx=%d" % (int(M.vx[s]) - int(M.vx[s0])),
                          "dvy=%d" % (int(M.vy[s]) - int(M.vy[s0])), "idx_eq" if M.idx_t[t1] == M.idx_t[t0] else "idx_ne",
                          "uniq" if len(hits) == 1 else "multi")] += 1
        if len(ex) < 12 and hits and hits[0][0] != s0:
            ex.append((rel, M.names.get(d), int(M.vx[s0]), [(int(M.vx[s]), int(M.vy[s]), int(M.enum_t[tpl[s]]), int(M.idx_t[tpl[s]])) for s, k in hits[:3]]))
    tot = collections.Counter()
    for rel in sorted(per):
        log.info("rel %+d: %s", rel, dict(per[rel]))
        tot.update(per[rel])
    for rel in sorted(rel_tab):
        log.info("source relation rel %+d: %s", rel, dict(rel_tab[rel].most_common(8)))
    for e in ex:
        log.info("  example %s", e)


if __name__ == "__main__":
    main()
