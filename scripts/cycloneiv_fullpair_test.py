#!/usr/bin/env python3.15t
"""Cyclone IV: is (asm frame, asm v) -> (plane frame, plane v) single-valued over the 399 honoured R4 arcs? (#165)  Read-only, 0 builds.

CONTEXT: sof->rbf is exact and asm v == sof v (#165), so a pure address function must map each asm CELL to one plane cell.
  An earlier test compared FRAME only (132 of 457 asm frames -> 2 plane frames); here v must match exactly (plane v = 6344 - asm v).
METHOD: per arc, group cells of the table's resolved record (asm frame fa, v va); candidate rigid shifts c (plane frame = c - fa,
  the mirror orientation the sof->rbf reversal implies; the + orientation is reported too) with ALL group cells inside the raw
  diff set ('on'); an arc is USED only if exactly one shift fits all cells (ambiguous / no-fit arcs are counted and left out).
PREDICTION (before the first run): no conflicts among full pairs.
REFUTED by: >= 5 % of asm cells (used arcs) mapping to two or more plane cells after v matches exactly.
Steps: (1) pairs, (2) conflicts + arcs + sources + raw element, (3) per-band offset table vs decompile bands (6057 / 5987 / 5917 ...,
  sof - asm = 6190 - plane_C, i.e. C = 133, 203, 273 ...), (4) re-resolve conflicting arcs over the other R4 records of the source fan-out.
Log tmp/logs/cycloneiv_fullpair_test.log; result tmp/fullpair/result.json.
"""
import bisect
import collections
import json
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_coordv2_validate as V  # noqa: E402

log = logging.getLogger("fullpair")
PV, PVMAX = V.PV, V.PVMAX
OUT = os.path.join(REPO, "tmp", "fullpair")


def group_cells(M, s, k):
    gi = int(M.gfirst[s]) + k
    a, b = int(M.gstart[gi]), int(M.gstart[gi]) + int(M.gsize[gi])
    sel = np.asarray(M.pred[a:b])
    pos = np.asarray(M.pos[a:b])[sel].astype(np.int64)
    return sorted(set(zip((pos % 6154).tolist(), (pos // 6154).tolist())))


def fits(cells, on_f_by_v, sign):
    """shifts c with plane frame = c - fa (sign=-1) or fa + c (sign=+1) putting every cell on a diff cell at v = PV - va."""
    cs = None
    for fa, va in cells:
        fr = on_f_by_v.get(PV - va, ())
        c = {(f + fa) if sign < 0 else (f - fa) for f in fr}
        cs = c if cs is None else cs & c
        if not cs:
            return set()
    return cs or set()


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_fullpair_test.log"), mode="w")])
    M = V.Model()
    A = V.arcs()
    log.info("arcs: %d", len(A))
    afx_cols = sorted(M.afx)
    band_starts = sorted(M.afx.values())

    def band(fa):
        i = bisect.bisect_right(band_starts, fa) - 1
        return band_starts[max(i, 0)]

    arcinfo = []
    for sign in (-1, +1):
        st = collections.Counter()
        for r in A:
            on = collections.defaultdict(list)
            for x in r["on"]:
                on[x % PVMAX].append(x // PVMAX)
            res = r.get("resolved")
            if not res:
                st["no_resolved"] += 1
                continue
            s = r["src"]
            fan = dict((d, k) for k, d in M.r4_fan(s))
            k = res.get("k")
            if res["rec"] in fan:
                k = fan[res["rec"]]
            cells = group_cells(M, s, k)
            cs = fits(cells, on, sign)
            if len(cs) == 1:
                st["unique"] += 1
            elif not cs:
                st["nofit"] += 1
            else:
                st["ambig"] += 1
            if sign < 0:
                arcinfo.append(dict(tile=r["tile"], I=r["I"], rel=r["rel"], src=s, Xs=M.src_col(s), rec=res["rec"], k=k,
                                    cells=cells, shifts=sorted(cs), n_on=len(r["on"])))
        log.info("[sign %+d] arcs: %s", sign, dict(st))
    # ---- step 1: pairs from uniquely-shifted arcs
    pairs = collections.defaultdict(lambda: collections.defaultdict(list))  # (fa,va) -> plane cell -> [arc idx]
    used = [i for i, a in enumerate(arcinfo) if len(a["shifts"]) == 1]
    for i in used:
        a = arcinfo[i]
        c = a["shifts"][0]
        for fa, va in a["cells"]:
            pairs[(fa, va)][(c - fa, PV - va)].append(i)
    n_cells = len(pairs)
    conf = {c: p for c, p in pairs.items() if len(p) > 1}
    n_pairs = sum(len(p) for p in pairs.values())
    log.info("used arcs %d; distinct asm cells %d; (asm cell, plane cell) pairs %d", len(used), n_cells, n_pairs)
    log.info("STEP2 conflicting asm cells (>=2 plane cells): %d / %d = %.2f %%", len(conf), n_cells, 100 * len(conf) / max(n_cells, 1))
    conf_arcs = collections.Counter()
    for c, p in conf.items():
        for pc, ids in p.items():
            for i in ids:
                conf_arcs[i] += 1
    log.info("arcs touching a conflict: %d of %d used", len(conf_arcs), len(used))
    for c, p in list(conf.items())[:25]:
        desc = []
        for pc, ids in p.items():
            desc.append("plane f%d: " % pc[0] + ",".join("X%dY%d/I%d src X%s rel%+d rec %d" % (
                arcinfo[i]["tile"][0], arcinfo[i]["tile"][1], arcinfo[i]["I"], arcinfo[i]["Xs"], arcinfo[i]["rel"], arcinfo[i]["rec"]) for i in ids[:3]))
        log.info("  asm cell %s: %s", c, " | ".join(desc))
    # ---- step 2b: frame-level collisions (same asm frame, different shift) and what separates them
    byf = collections.defaultdict(lambda: collections.defaultdict(list))
    for i in used:
        a = arcinfo[i]
        for fa, va in a["cells"]:
            byf[fa][a["shifts"][0] - 0].append((va, a["Xs"], a["rel"], i))
    fconf = {fa: d for fa, d in byf.items() if len(d) > 1}
    log.info("STEP2b asm frames with >=2 shifts: %d of %d frames; shared (fa,va) cells: %d", len(fconf), len(byf),
             sum(1 for p in pairs.values() if sum(len(x) for x in p.values()) > 1))
    sep = collections.Counter()
    for fa, d in fconf.items():
        vs = {c: {v for v, *_ in lst} for c, lst in d.items()}
        allv = [v for s_ in vs.values() for v in s_]
        sep["v sets disjoint" if len(allv) == len(set(allv)) else "v shared"] += 1
        lanes = {c: {(v - 1) // 793 for v in s_} for c, s_ in vs.items()}
        sep["lane sets disjoint" if len({l for s_ in lanes.values() for l in s_}) == sum(len(s_) for s_ in lanes.values()) else "lane overlap"] += 1
    log.info("STEP2b collisions: %s", dict(sep))
    for fa in sorted(fconf)[:10]:
        log.info("  fa %d: %s", fa, {c: [(v, X, rl) for v, X, rl, _ in lst] for c, lst in fconf[fa].items()})
    # ---- shift vs source column
    byX = collections.defaultdict(collections.Counter)
    for i in used:
        a = arcinfo[i]
        byX[a["Xs"]][a["shifts"][0]] += 1
    multi = {X: dict(c) for X, c in byX.items() if len(c) > 1}
    log.info("used-arc shifts by source column: %d columns, %d with >1 shift value", len(byX), len(multi))
    # ---- step 3: bands over non-conflicting cells
    nonconf = {c: next(iter(p)) for c, p in pairs.items() if len(p) == 1}
    bands = collections.defaultdict(collections.Counter)
    for (fa, va), (pf, pv) in nonconf.items():
        bands[band(fa)][pf + fa] += 1
    sofoff = {}
    log.info("STEP3 band (asm start) -> C (plane = C - fa): count; decompile C = 6190 - sof_offset")
    tab = []
    for b in sorted(bands):
        c = bands[b]
        top = c.most_common(3)
        tab.append((b, top))
        log.info("  band %d: %s", b, top)
    # decompile: 6057 at band 58? frames 60..74 -> band start 58; then 5987 @93, 5917 @130(128?), -70 per band
    log.info("decompile C reference: 133 (frames 60..74), 203 (93..109), 273 (130..141), +70 per band; differences listed above")
    # ---- step 3b: against the decompile agent's per-frame offsets (sample of assembler entries pushed through the exact sof map)
    smp = os.path.join(REPO, "vendor-analysis", "altera", "oracle", "asm_vs_repo_sample.npy")
    if os.path.exists(smp):
        p, sof = np.load(smp)
        fa_s, sf = p % 6154, sof % 6154
        cdec = {}
        order = np.argsort(fa_s, kind="stable")
        fa_o, off_o = fa_s[order], (6190 - sf - fa_s)[order]
        for f in np.unique(fa_o):
            seg = off_o[np.searchsorted(fa_o, f):np.searchsorted(fa_o, f, side="right")]
            u, c = np.unique(seg, return_counts=True)
            cdec[int(f)] = int(u[np.argmax(c)])      # C_dec: plane = C_dec - fa
        dl = collections.defaultdict(collections.Counter)
        nomatch = 0
        for i in used:
            a = arcinfo[i]
            for fa, va in a["cells"]:
                if fa in cdec:
                    dl[a["rel"]][a["shifts"][0] - cdec[fa]] += 1
                else:
                    nomatch += 1
        log.info("STEP3b frames with decompile offset: %d; arc cells without: %d", len(cdec), nomatch)
        for rel in sorted(dl):
            log.info("  rel %+d: arc C - decompile C : %s", rel, dict(dl[rel].most_common(8)))
        dx = collections.Counter()
        for i in used:
            a = arcinfo[i]
            for fa, va in a["cells"]:
                dx[a["shifts"][0] - cdec[fa] - int(M.g.FX[a["Xs"]])] += 1
        log.info("STEP3b (arc C - decompile C - FX[source col]): %s", dict(dx.most_common(10)))
        eq = sum(c for r_ in dl.values() for d, c in r_.items() if d == 0)
        tot = sum(c for r_ in dl.values() for c in r_.values())
        log.info("STEP3b arc cells whose C equals the decompile C: %d / %d", eq, tot)
    # ---- step 4: re-resolve conflicting arcs
    consensus = {}
    for (fa, va), (pf, pv) in nonconf.items():
        consensus[(fa, va)] = pf
    fixed = collections.Counter()
    for i in sorted(conf_arcs):
        a = arcinfo[i]
        r = [x for x in A if x["src"] == a["src"] and x["tile"] == a["tile"] and x["I"] == a["I"]][0]
        on = collections.defaultdict(list)
        for x in r["on"]:
            on[x % PVMAX].append(x // PVMAX)
        alts = []
        for k, d in M.r4_fan(a["src"]):
            if d == a["rec"]:
                continue
            cs = fits(group_cells(M, a["src"], k), on, -1)
            if len(cs) == 1:
                alts.append((d, k, next(iter(cs))))
        fixed["arc with alt full-fit record"] += bool(alts)
        fixed["arc total"] += 1
        a["alts"] = alts
    log.info("STEP4 %s", dict(fixed))
    json.dump(dict(n_used=len(used), n_cells=n_cells, n_conf=len(conf), arcinfo_n=len(arcinfo),
                   conf_cells=[list(c) for c in conf][:200], by_band=[(b, t) for b, t in tab]),
              open(os.path.join(OUT, "result.json"), "w"))


if __name__ == "__main__":
    main()
