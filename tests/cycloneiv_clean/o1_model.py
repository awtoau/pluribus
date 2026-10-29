"""LAB LUT-bit address model (A3) from vendor files + the specimen oracle (observed.npz of scripts/cycloneiv_clean_lut_specimens.py).

Nothing here reads lifters/data/*geom*.json.  Inputs:
- hi[r], lo[c]: asmdb LAB instance cell vector (body.bin, 104 x 90 cells, value = hi << 16 | lo; hi -70 per row, lo per column).
- (dx, dy): blkrba table (x_cum, y_cum) of RBLUT{k}.
- LAB column X list: fitter probe (lifters/data/cycloneiv_ep4cgx150_labs.json, vendor tool output, error 171016).
Hypotheses (pairing, signs) are scored against observed cells; the two frame / v constants are FITTED (mode over all observed cells).
"""
import collections
import csv
import json
import os
import re
import struct

import numpy as np

from conftest import REPO, VA
from lifters.cycloneiv_clean import plane as P

S1 = os.path.join(VA, "inventory", "s1")
BODY = os.path.join(S1, "asmdb", "body.bin")
BLK = os.path.join(S1, "blkrba_stingray_abs.csv")
LABS = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_labs.json")
OBS = os.path.join(REPO, "tmp", "cycloneiv_clean", "lut_specimens", "observed.npz")
W = P.FRAMES
COLS, ROWS_, LES, KS = 104, 90, 16, 16


def instance_cells():
    """(hi0, lo[104]) from the asmdb body: the 9,360-entry delta vector whose hi steps -70 per row and lo is constant per column."""
    b = open(BODY, "rb").read()
    n = COLS * ROWS_
    pat = struct.pack("<I", n)
    p = b.find(pat, 0x1000)
    while p >= 0:
        if p + 4 + 4 * n <= len(b):
            cs = np.cumsum(np.array(struct.unpack_from("<%di" % n, b, p + 4), np.int64)) & 0xFFFFFFFF
            h, lo = (cs >> 16).reshape(COLS, ROWS_), (cs & 0xFFFF).reshape(COLS, ROWS_)
            if (np.diff(h, axis=1) == -70).all() and (lo == lo[:, :1]).all() and len(set(h[:, 0].tolist())) == 1:
                return int(h[0, 0]), lo[:, 0]
        p = b.find(pat, p + 1)
    raise AssertionError("asmdb LAB instance cell vector not found")


def blkrba():
    """dx[le, k], dy[le, k] from the blkrba table."""
    tab = {}
    for row in csv.DictReader(open(BLK)):
        m = re.match(r"^L:(\d+):RBLUT(\d+)$", row["name"])
        if m:
            tab[(int(m[1]), int(m[2]))] = (int(row["x_cum"]), int(row["y_cum"]))
    dx = np.array([[tab[(a, b)][0] for b in range(KS)] for a in range(LES)])
    dy = np.array([[tab[(a, b)][1] for b in range(KS)] for a in range(LES)])
    return dx, dy


def lab_columns():
    """Sorted LAB column X values (104) and the row Y values (1..90) of the fitter-probed legal LAB sites."""
    labs = json.load(open(LABS))["labs"]
    xs = sorted({x for x, _ in labs})
    ys = sorted({y for _, y in labs})
    assert len(xs) == COLS and ys == list(range(1, ROWS_ + 1)), (len(xs), ys[:3], ys[-3:])
    return xs, ys


def addresses(c, r, le, k, hi0, lo, dx, dy, sx, sy):
    """Asm address of LUT bit (column rank c, row r, LE le, RBLUT index k): (hi0 - 70 r + sx dx) W + lo[c] + sy dy."""
    return (hi0 - 70 * r + sx * dx[le, k]) * W + lo[c] + sy * dy[le, k]


def observed():
    o = np.load(OBS)
    return {k: o[k] for k in o.files}


def obs_sof(o):
    """Observed cells as (sof frame s, sof v) assuming no mirror (valid where the mask cell is not mirrored)."""
    return W - 1 - o["r"], P.jk_to_v(o["j"], o["k"])


def site_cells(o):
    """Observed plane cells per site: int array [n_sites, 16] indexed by INIT bit, cell id = (r * 800 + j) * 8 + k."""
    n = len(o["sx"])
    out = np.full((n, 16), -1, np.int64)
    out[o["site"], o["bit"]] = (o["r"] * 800 + o["j"]) * 8 + o["k"]
    return out


def predicted_sof(site_c, site_r, site_le, hi0, lo, dx, dy, sx, sy):
    """Predicted (s, v) per site and RBLUT index k, constants not yet applied: arrays [n_sites, 16]."""
    k = np.arange(16)[None, :]
    a = addresses(site_c[:, None], site_r[:, None], site_le[:, None], k, hi0, lo, dx, dy, sx, sy)
    return a % W, a // W


def fit_constants(pred, obs_cells):
    """Mode of (s_obs - s_pred, v_obs - v_pred) over all (observed cell, predicted cell) pairs of the same site.
    Observed cells are mapped back to sof (s, v) without the mirror (right wherever the cell is not mirrored)."""
    s0, v0 = pred
    r, rest = obs_cells // (800 * 8), obs_cells % (800 * 8)
    j, k = rest // 8, rest % 8
    so, vo = W - 1 - r, P.jk_to_v(j, k)
    cnt = collections.Counter()
    for a in range(so.shape[0]):
        ds = (so[a][:, None] - s0[a][None, :]).ravel()
        dv = (vo[a][:, None] - v0[a][None, :]).ravel()
        cnt.update(zip(ds.tolist(), dv.tolist()))
    (cs, cv), n = cnt.most_common(1)[0]
    return cs, cv, n


def predicted_cells(pred, cs, cv, tables):
    """Plane cell ids [n_sites, 16] (-1 outside the CRAM) of the predicted sof cells after the constants, A5 incl. mirror."""
    s, v = pred[0] + cs, pred[1] + cv
    ok = (s >= 0) & (s < W) & (v >= 0) & (v < P.BITS_PER_FRAME)
    r, j, k = P.sof_to_rbf(np.where(ok, v * W + s, 0), tables)
    return np.where(ok, (r * 800 + j) * 8 + k, -1)


def site_matches(pc, oc):
    """Per site: the 16 predicted cells equal the 16 observed cells as a set."""
    return np.array([sorted(a.tolist()) == sorted(b.tolist()) for a, b in zip(pc, oc)])


def bit_permutations(pc, oc):
    """Per site: p[b] = RBLUT index whose predicted cell is the observed cell of INIT bit b (-1 if none)."""
    out = np.full(oc.shape, -1, np.int64)
    for a in range(oc.shape[0]):
        where = {int(c): i for i, c in enumerate(pc[a])}
        for b in range(16):
            out[a, b] = where.get(int(oc[a, b]), -1)
    return out


def is_index_bit_permutation(p):
    """p[b] (16 values) is a permutation of the 4 index bits: p(b) = XOR of the images of the set bits of b."""
    if (p < 0).any() or p[0] != 0:
        return False
    img = [int(p[1 << i]) for i in range(4)]
    if sorted(img) != [1, 2, 4, 8]:
        return False
    return all(int(p[b]) == sum(img[i] for i in range(4) if b >> i & 1) for b in range(16))
