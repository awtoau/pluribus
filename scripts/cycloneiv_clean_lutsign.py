#!/usr/bin/env python3.15t
"""LUT address sign variants under sof_identity_reversed (#165).  Constants fitted from ONE anchor cell, hits counted on all others.
Log: tmp/logs/cycloneiv_clean_lutsign.log"""
import csv, json, os, re, sys, collections
import numpy as np
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from lifters.cycloneiv_clean import plane as P
VA = os.path.join(REPO, "vendor-analysis", "altera", "inventory", "s1")
lo_by_rank = np.array([int(r["asm_cell_lo"]) for r in csv.DictReader(open(os.path.join(VA, "asmdb", "frame_table.csv"))) if r["kind"] == "LAB"])
tab = {}
for row in csv.DictReader(open(os.path.join(VA, "blkrba_stingray_abs.csv"))):
    m = re.match(r"^L:(\d+):RBLUT(\d+)$", row["name"])
    if m: tab[(int(m[1]), int(m[2]))] = (int(row["x_cum"]), int(row["y_cum"]))
g = json.load(open(os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_geom.json")))
labs = sorted(int(x) for x, kd in g["col_kind"].items() if kd == "LAB")
FX = {int(k): v for k, v in g["FX"].items()}
c, r, le, k = np.meshgrid(np.arange(104), np.arange(90), np.arange(16), np.arange(16), indexing="ij")
dx = np.vectorize(lambda a, b: tab[(a, b)][0])(le, k); dy = np.vectorize(lambda a, b: tab[(a, b)][1])(le, k)
hi = 6252 - 70 * r; lo = lo_by_rank[c]
tm = P.load_tables()
out = open(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_lutsign.log"), "w")
def log(*a):
    s = " ".join(map(str, a)); print(s); out.write(s + "\n")
for pairing in ("rtl", "ltr"):
    cols = labs[::-1] if pairing == "rtl" else labs
    pf = (np.array([FX[x] for x in cols])[c] + dy - 15).ravel(); pv = (g["vy0"] + g["vpitch"] * (r + 1) + 2 - dx).ravel()
    for sx in (1, -1):
        for sy in (1, -1):
            a = ((hi + sx * dx) * 6154 + lo + sy * dy).ravel()
            # fit constants from anchor 0: shift sof frame by cf, v by cv
            r0, j0, k0 = P.sof_to_rbf(a[:1], tm)
            cf = int(pf[0] - 37 - r0[0])       # rbf frame shift (applied as sof frame -cf)
            cv = int(pv[0] - P.plane_v(j0, k0)[0])
            s, v = a % 6154, a // 6154
            s2 = s - cf; v2 = v - cv
            ok = (s2 >= 0) & (s2 < 6154) & (v2 >= 0) & (v2 < 6344)
            a2 = np.where(ok, v2 * 6154 + s2, 0)
            rr, jj, kk = P.sof_to_rbf(a2, tm)
            hit = ok & (P.plane_frame(rr) == pf) & (P.plane_v(jj, kk) == pv)
            log(pairing, "sx", sx, "sy", sy, "const frame", cf, "v", cv, "hits", int(hit.sum()), "/", a.size, f"{100*hit.mean():.3f}%")
            if hit.mean() < 1 and hit.sum():
                h = hit.reshape(104, 90, 16, 16)
                log("   per-LE hits", h.sum(axis=(0, 1, 3)).tolist()); log("   per-k hits", h.sum(axis=(0, 1, 2)).tolist())
