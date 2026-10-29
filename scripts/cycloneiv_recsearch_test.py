#!/usr/bin/env python3.15t
"""Cyclone IV: which fan-out record of the source LE_BUFFER fits each R4 arc with the asm->sof frame offsets FIXED to the decompile table? (#165)  0 builds.
Offsets: per asm frame, mode of (sof frame - asm frame) over the decompile sample (oracle/asm_vs_repo_sample.npy); a frame absent from the
  sample takes the offset of the nearest sampled frame (nearest-band rule). No free shift.
Search: ALL records of the source's fan-out (not only R4, not only the table's resolved record); fit = every programmed group cell
  (sof frame = fa + offset, sof v = asm v) inside the arc's raw diff converted to sof space (exact map, mirrored blocks included).
PREDICTION (before the run): >= 95 % of the 379 arcs have exactly one fitting record; for rel 0 / rel +4 arcs it is a twin of the resolved
  record (same direction and template index, vx differing by two column pitches).
REFUTED by: < 90 % of arcs with a unique record, or rel 0 / +4 fitting records not twins of the resolved one.
Log tmp/logs/cycloneiv_recsearch_test.log.
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
import cycloneiv_sofframe_test as SF  # noqa: E402

log = logging.getLogger("recsearch")


def offsets():
    pp, sof = np.load(os.path.join(REPO, "vendor-analysis", "altera", "oracle", "asm_vs_repo_sample.npy"))
    fa, d = pp % 6154, (sof % 6154) - pp % 6154
    keys, off = [], []
    for f in np.unique(fa):
        u, c = np.unique(d[fa == f], return_counts=True)
        keys.append(int(f))
        off.append(int(u[np.argmax(c)]))
    return np.array(keys), np.array(off)


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_recsearch_test.log"), mode="w")])
    M = V.Model()
    keys, offv = offsets()
    nearest = {}

    def off(fa):
        if fa not in nearest:
            nearest[fa] = (int(offv[np.argmin(np.abs(keys - fa))]), int(np.min(np.abs(keys - fa))))
        return nearest[fa][0]

    per = collections.defaultdict(collections.Counter)
    twin = collections.defaultdict(collections.Counter)
    rows = []
    n_near = 0
    for r in V.arcs():
        res = r.get("resolved")
        if not res:
            continue
        s, rel = r["src"], r["rel"]
        sf, sv, _, ok = SF.plane_to_sof(r["on"])
        diff = set(zip(sf.tolist(), sv.tolist()))
        hits = []
        for k, d in enumerate(M.D.fan_of(s).tolist()):
            cells = FP.group_cells(M, s, k)
            if cells and all((fa + off(fa), va) in diff for fa, va in cells):
                hits.append((k, d, len(cells)))
        hits_n = [h for h in hits if h[2] >= 2]       # 1-cell groups fit by chance; counted separately
        c = "unique" if len(hits) == 1 else ("none" if not hits else "multi")
        per[rel][c] += 1
        per[rel]["multi_ge2cells"] += len(hits_n) > 1
        t = res["rec"]
        for k, d, n in hits:
            if len(hits) == 1:
                tp = M.D.tpl
                twin[rel][("same" if d == t else "other",
                           "dvx=%d" % (int(M.vx[d]) - int(M.vx[t])),
                           "idx_eq" if M.idx_t[tp[d]] == M.idx_t[tp[t]] else "idx_ne",
                           "dir_eq" if M.dir_t[tp[d]] == M.dir_t[tp[t]] else "dir_ne")] += 1
                rows.append((rel, r["tile"][0], M.src_col(s), M.names.get(d), M.names.get(t), int(M.vx[d]), int(M.vx[s])))
    tot = collections.Counter()
    for rel in sorted(per):
        log.info("rel %+d: %s", rel, dict(per[rel]))
        tot.update(per[rel])
    n = tot["unique"] + tot["none"] + tot["multi"]
    log.info("arcs %d: unique %d (%.1f %%), none %d, multi %d", n, tot["unique"], 100 * tot["unique"] / n, tot["none"], tot["multi"])
    log.info("frames resolved by nearest-band rule: %d of %d, max distance %d", sum(1 for v in nearest.values() if v[1] > 0), len(nearest),
             max((v[1] for v in nearest.values()), default=0))
    for rel in sorted(twin):
        log.info("twin relation rel %+d (unique-hit arcs): %s", rel, dict(twin[rel].most_common(8)))
    # ---- diagnostic: allow one extra shift on top of the fixed table, over the whole fan-out
    ext = collections.defaultdict(collections.Counter)
    for r in V.arcs():
        res = r.get("resolved")
        if not res or r["rel"] not in (0, 4):
            continue
        s_ = r["src"]
        sf, sv, _, ok = SF.plane_to_sof(r["on"])
        diff = set(zip(sf.tolist(), sv.tolist()))
        found = set()
        for k, d in enumerate(M.D.fan_of(s_).tolist()):
            cells = FP.group_cells(M, s_, k)
            if len(cells) < 2:
                continue
            for x in range(-210, 211):
                if all((fa + off(fa) + x, va) in diff for fa, va in cells):
                    found.add(("resolved" if d == res["rec"] else "other", x))
        ext[r["rel"]][tuple(sorted(found)) if len(found) <= 2 else "many"] += 1
    for rel in sorted(ext):
        log.info("extra-shift diagnostic rel %+d (record, extra shift) sets: %s", rel, dict(ext[rel].most_common(8)))
    # name relation: fitting record name tile x vs RCF tile x and source col
    rel_tab = collections.defaultdict(collections.Counter)
    for rel, tx, Xs, nm, nt, vxd, vxs in rows:
        rel_tab[rel][(vxd - vxs)] += 1
    for rel in sorted(rel_tab):
        log.info("fitting record vx - source vx, rel %+d: %s", rel, dict(rel_tab[rel].most_common(6)))
    for row in rows[:12]:
        log.info("  sample rel %+d tileX %s srcX %s fit %s resolved %s", *row[:5])


if __name__ == "__main__":
    main()
