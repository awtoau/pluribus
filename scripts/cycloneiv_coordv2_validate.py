#!/usr/bin/env python3.15t
"""Cyclone IV coordinate model v2: offline validation against the forced LB -> R4 arcs (#157, #160, #162).  Read-only, 0 builds.

MODEL (independent review, claims F1-F3):
  F1  asm column base of LAB column X is afx[115 - vx(X)] (vendor x label), not afx[X] (V4 names label C - 2).
  F2  resolved record: vx = source vx - rel, R + vy = 91 (name H4R<R>C<C>), template index = name k (RT) or k + 17 (LT).
  F3  mirror about the SOURCE tile: plane_frame = FX[Xs] + ABASE[Xs] + 17 - asm_frame, plane_v = 6344 - asm_v,
      Xs = the source record's LAB column, ABASE[Xs] = afx[115 - vx(Xs)].
PREDICTION (written before the first run): for >= 383 of the 399 arcs (unique (src, tile, I) of tmp/hop_specimens/results_r4*.json,
  honoured) exactly ONE R4 record of the source's fan-out has all its programmed group cells inside the raw diff ('on') under
  F3 with no free shift and no table; the 16 misses are sources X27..X30 / X85..X88, which resolve with the X29/X87 anchor.
REFUTED by: < 90 % (359 of 399) arcs with a unique hit, or any arc whose unique record is not the table's resolved record,
  or a unique record that breaks F2.
Log tmp/logs/cycloneiv_coordv2_validate.log.
"""
import collections
import glob
import json
import logging
import os
import pickle
import re
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_ddb_trace as DT  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402

log = logging.getLogger("coordv2_validate")
TMP = os.path.join(REPO, "tmp", "ddb")
PV, PVMAX = 6344, 6368
R4_ENUM = 268
XM = 115
NAME = re.compile(r"^H4R(\d+)C(\d+)(RT|LT)\[(\d+)\]$")
ANCHOR_FIX = {29: 4, 87: 4}     # step-1 variant: plane anchor FX + 4 at X29 / X87


def arcs():
    rows = {}
    for f in sorted(glob.glob(os.path.join(REPO, "tmp/hop_specimens/results_r4*.json"))):
        for r in json.load(open(f))["rows"]:
            if r.get("wire") == "R4" and r.get("honoured") and r.get("cands"):
                r["rel"] = r.get("rel", r["lb"][1] - r["tile"][0])
                rows.setdefault((r["src"], tuple(r["tile"]), r["I"]), r)
    return list(rows.values())


class Model:
    def __init__(self):
        self.D = DT.Ddb(need_map=False)
        D = self.D
        self.g = cg.load("ep4cgx150")
        self.afx = {int(k): v for k, v in json.load(open(os.path.join(TMP, "stingray4_dec_afx.json"))).items()}
        z = np.load(os.path.join(TMP, "stingray4_rt_fanout.npz"))
        self.enum_t, self.idx_t, self.dir_t = z["enum"], z["index"], z["direction"]
        grec = np.load(os.path.join(TMP, "stingray4_dec_grec.npy"), mmap_mode="r")
        ng = np.bincount(np.asarray(grec), minlength=len(D.tpl))
        self.gfirst = np.concatenate([[0], np.cumsum(ng)[:-1]])
        self.gstart = np.load(os.path.join(TMP, "stingray4_dec_gstart.npy"), mmap_mode="r")
        self.gsize = np.load(os.path.join(TMP, "stingray4_dec_gsize.npy"), mmap_mode="r")
        self.pred = np.load(os.path.join(TMP, "stingray4_dec_pred.npy"), mmap_mode="r")
        self.pos = np.load(os.path.join(TMP, "stingray4_asm_pos.npy"), mmap_mode="r")
        self.names = pickle.load(open(os.path.join(TMP, "stingray4_dec_names.pkl"), "rb"))
        self.vx, self.vy = D.P.vx, D.P.vy

    def abase(self, X):
        return self.afx[XM - self.D.cm[X]]

    def src_col(self, s):
        return self.D.x_of_vx.get(int(self.vx[s]))

    def cells(self, s, k, Xs, anchor_fix=False):
        """programmed plane cells (flat) of group k of record s, placed by F3 about source column Xs."""
        gi = int(self.gfirst[s]) + k
        a, b = int(self.gstart[gi]), int(self.gstart[gi]) + int(self.gsize[gi])
        sel = np.asarray(self.pred[a:b])
        pos = np.asarray(self.pos[a:b])[sel].astype(np.int64)
        fa, va = pos % 6154, pos // 6154
        fx = self.g.FX[Xs] + (ANCHOR_FIX.get(Xs, 0) if anchor_fix else 0)
        return (fx + self.abase(Xs) + 17 - fa) * PVMAX + (PV - va)

    def r4_fan(self, s):
        out = []
        for k, d in enumerate(self.D.fan_of(s).tolist()):
            if self.enum_t[self.D.tpl[d]] == R4_ENUM:
                out.append((k, d))
        return out

    def f2_ok(self, s, d, rel):
        t = self.D.tpl[d]
        m = NAME.match(self.names.get(d, ""))
        if not m:
            return False
        R, _c, lr, k = int(m[1]), m[2], m[3], int(m[4])
        return (int(self.vx[d]) == int(self.vx[s]) - rel and R + int(self.vy[d]) == 91
                and int(self.idx_t[t]) == (k if lr == "RT" else k + 17))


def classify(M, r, anchor_fix=False):
    s, rel = r["src"], r["rel"]
    Xs = M.src_col(s)
    on = set(r["on"])
    hits = []
    for k, d in M.r4_fan(s):
        c = M.cells(s, k, Xs, anchor_fix)
        if len(c) and all(int(x) in on for x in c.tolist()):
            hits.append((k, d))
    return Xs, hits


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_coordv2_validate.log"), mode="w")])
    M = Model()
    A = arcs()
    log.info("arcs (unique src, tile, I; honoured, with cands): %d", len(A))
    for variant in (False, True):
        tag = "anchor fix X29/X87" if variant else "plain F3"
        per = collections.defaultdict(lambda: collections.Counter())
        miss_cols = collections.Counter()
        bad_tab, bad_f2, n_res_cmp = [], [], 0
        for r in A:
            Xs, hits = classify(M, r, variant)
            u = len(hits) == 1
            per[r["rel"]]["unique" if u else ("none" if not hits else "multi")] += 1
            if not u:
                miss_cols[Xs] += 1
                continue
            d = hits[0][1]
            res = r.get("resolved")
            if res:
                n_res_cmp += 1
                if res["rec"] != d:
                    bad_tab.append((r["tile"], r["I"], r["rel"], M.names.get(d), M.names.get(res["rec"])))
            if not M.f2_ok(r["src"], d, r["rel"]):
                bad_f2.append((r["tile"], r["I"], r["rel"], M.names.get(d)))
        tot = collections.Counter()
        for rel in sorted(per):
            log.info("[%s] rel %+d: %s", tag, rel, dict(per[rel]))
            tot.update(per[rel])
        n = len(A)
        log.info("[%s] unique hits %d / %d = %.1f %%; none %d; multi %d", tag, tot["unique"], n, 100 * tot["unique"] / n, tot["none"], tot["multi"])
        log.info("[%s] misses by source column: %s", tag, dict(sorted(miss_cols.items())))
        log.info("[%s] unique record != table's resolved record: %d of %d compared %s", tag, len(bad_tab), n_res_cmp, bad_tab[:8])
        log.info("[%s] unique record breaking F2 (vx, R+vy=91, idx rule): %d %s", tag, len(bad_f2), bad_f2[:8])


if __name__ == "__main__":
    main()
