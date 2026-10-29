"""O1: LUT INIT cells.  2,396,160 asm addresses (local asmdb decode) vs the LUT-mask law cells (oracle: Quartus corpus builds).

The law (frame FX + dy - 15, v = v0 + 2 - dx) and its per-column FX are ORACLE data here, never an input of lifters/cycloneiv_clean.
Candidates of the open address -> plane interface are scored per column pairing (instance rank vs column, right-to-left / left-to-right).
Candidate not at 100 % -> xfail with the number; the number is logged to tmp/logs/cycloneiv_clean_oracles.log.
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


def test_o1_open_interface_not_chosen():
    with pytest.raises(NotImplementedError):
        P.address_to_plane(0)
