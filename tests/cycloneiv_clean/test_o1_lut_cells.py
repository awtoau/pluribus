"""O1: LUT INIT cells.  2,396,160 asm addresses (local asmdb decode) vs the LUT-mask law cells (oracle: Quartus corpus builds).

The law (frame FX + dy - 15, v = v0 + 2 - dx) and its per-column FX are ORACLE data here, never an input of lifters/cycloneiv_clean.
Candidates of the open address -> plane interface are scored per column pairing (instance rank vs column, right-to-left / left-to-right).
Candidates (raw asmdb addresses, old sign) and the sign variants below; not at 100 % -> xfail with the number; the number is logged to tmp/logs/cycloneiv_clean_oracles.log.
"""
import csv
import json
import os
import re

import numpy as np
import pytest

from conftest import REPO, VA, need, report
from lifters.cycloneiv_clean import plane as P

ADDR = os.path.join(VA, "inventory", "s1", "asmdb", "lut_asm_addr.npy")
BLK = os.path.join(VA, "inventory", "s1", "blkrba_stingray_abs.csv")
FT = os.path.join(VA, "inventory", "s1", "asmdb", "frame_table.csv")
GEOM = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_geom.json")
N = 104 * 90 * 16 * 16


def law_cells(pairing):
    g = json.load(open(GEOM))
    fx = {int(k): v for k, v in g["FX"].items()}
    labs = sorted((x for x, kd in g["col_kind"].items() if kd == "LAB"), key=int)
    labs = [int(x) for x in labs]
    labs = labs[::-1] if pairing == "rtl" else labs
    tab = {}
    for row in csv.DictReader(open(BLK)):
        m = re.match(r"^L:(\d+):RBLUT(\d+)$", row["name"])
        if m:
            tab[(int(m[1]), int(m[2]))] = (int(row["x_cum"]), int(row["y_cum"]))
    c, r, le, k = np.meshgrid(np.arange(104), np.arange(90), np.arange(16), np.arange(16), indexing="ij")
    dx = np.vectorize(lambda a, b: tab[(a, b)][0])(le, k)
    dy = np.vectorize(lambda a, b: tab[(a, b)][1])(le, k)
    fxc = np.array([fx[x] for x in labs])[c]
    return (fxc + dy - 15).ravel(), (g["vy0"] + g["vpitch"] * (r + 1) + 2 - dx).ravel()


@pytest.fixture(scope="module")
def addr():
    need(ADDR, BLK, GEOM)
    a = np.load(ADDR)
    assert a.shape == (N,) and len(np.unique(a)) == N
    return a


@pytest.fixture(scope="module", params=["rtl", "ltr"])
def law(request):
    return request.param, law_cells(request.param)


@pytest.mark.parametrize("cand", sorted(P.CANDIDATES))
def test_o1_candidate(cand, addr, law, tables):
    pairing, (pf, pv) = law
    r, j, k = P.CANDIDATES[cand](addr, tables)
    okf = (r >= 0) & (P.plane_frame(r) == pf)
    okv = P.plane_v(j, k) == pv
    both = int((okf & okv).sum())
    report("O1", candidate=cand, pairing=pairing, cells=N, frame_ok=int(okf.sum()), v_ok=int(okv.sum()), both=both)
    if both != N:
        pytest.xfail(f"{cand}/{pairing}: {both}/{N} cells (frame {int(okf.sum())}, v {int(okv.sum())})")


def lut_parts():
    """Components of the asmdb LUT formula: hi[r], lo[c] (instance cells), blkrba (dx, dy); index [c, r, le, k]."""
    lo_rank = np.array([int(x["asm_cell_lo"]) for x in csv.DictReader(open(FT)) if x["kind"] == "LAB"])
    tab = {}
    for row in csv.DictReader(open(BLK)):
        m = re.match(r"^L:(\d+):RBLUT(\d+)$", row["name"])
        if m:
            tab[(int(m[1]), int(m[2]))] = (int(row["x_cum"]), int(row["y_cum"]))
    c, r, le, k = np.meshgrid(np.arange(104), np.arange(90), np.arange(16), np.arange(16), indexing="ij")
    dx = np.vectorize(lambda a, b: tab[(a, b)][0])(le, k)
    dy = np.vectorize(lambda a, b: tab[(a, b)][1])(le, k)
    return 6252 - 70 * r, lo_rank[c], dx, dy


@pytest.mark.parametrize("pairing", ["rtl", "ltr"])
@pytest.mark.parametrize("sx", [1, -1])
@pytest.mark.parametrize("sy", [1, -1])
def test_o1_sign_variants(pairing, sx, sy, tables):
    """address_to_plane on (hi + sx*dx) * 6154 + lo + sy*dy + const, const pair fitted from ONE cell, hits counted on all cells.
    Expected: only ltr / sx +1 / sy -1 (in-column offset of the blkrba table negated, columns ascending) reaches 100 %."""
    need(FT, BLK, GEOM)
    hi, lo, dx, dy = lut_parts()
    pf, pv = law_cells(pairing)
    a = ((hi + sx * dx) * 6154 + lo + sy * dy).ravel()
    r0, j0, k0 = P.address_to_plane(a[:1], tables)
    cf = int(pf[0] - P.RBF_PRE_FRAMES - r0[0])
    cv = int(pv[0] - P.plane_v(j0, k0)[0])
    s, v = a % 6154 - cf, a // 6154 - cv
    ok = (s >= 0) & (s < 6154) & (v >= 0) & (v < 6344)
    r, j, k = P.address_to_plane(np.where(ok, v * 6154 + s, 0), tables)
    hit = int((ok & (P.plane_frame(r) == pf) & (P.plane_v(j, k) == pv)).sum())
    report("O1-sign", pairing=pairing, sx=sx, sy=sy, frame_const=cf, v_const=cv, hits=hit, cells=N)
    if (pairing, sx, sy) == ("ltr", 1, -1):
        assert hit == N
    elif hit != N:
        pytest.xfail(f"{pairing} sx={sx} sy={sy}: {hit}/{N}")


def test_o1_address_to_plane_is_sof_identity(tables):
    a = np.array([0, 1, 6153, 6154, 39_040_975])
    for x, y in zip(P.address_to_plane(a, tables), P.sof_to_rbf(a, tables)):
        assert (x == y).all()
