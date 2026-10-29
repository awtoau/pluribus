"""O1: LAB LUT-bit cells.  Model = asmdb formula (hi[r], lo[c], blkrba dx / dy) -> sof identity -> A5.
Oracle = Quartus-built specimens (scripts/cycloneiv_clean_lut_specimens.py): which rbf cells flip when a LUT INIT bit flips.

No geometry JSON is read.  Constants: none inherited; the frame constant is the mode over all specimen cells and must hold for every site.
Skips without vendor-analysis/ or the specimen build (tmp/cycloneiv_clean/lut_specimens/observed.npz).
Numbers go to tmp/logs/cycloneiv_clean_oracles.log.
"""
import itertools
import os

import numpy as np
import pytest

import o1_model as M
from conftest import need, report
from lifters.cycloneiv_clean import plane as P

N = M.COLS * M.ROWS_ * M.LES * M.KS


@pytest.fixture(scope="module")
def model():
    need(M.BODY, M.BLK, M.LABS, M.OBS)
    hi0, lo = M.instance_cells()
    dx, dy = M.blkrba()
    xs, _ = M.lab_columns()
    o = M.observed()
    return dict(hi0=hi0, lo=lo, dx=dx, dy=dy, xs=xs, o=o, oc=M.site_cells(o))


def predict(m, colp, rowp, sx, sy, tables):
    o = m["o"]
    rank = np.array([m["xs"].index(x) for x in o["sx"]])
    c = rank if colp == "ltr" else M.COLS - 1 - rank
    r = (o["sy"] - 1) if rowp == "asc" else M.ROWS_ - o["sy"]
    pred = M.predicted_sof(c, r, o["le"], m["hi0"], m["lo"], m["dx"], m["dy"], sx, sy)
    cs, cv, votes = M.fit_constants(pred, m["oc"])
    pc = M.predicted_cells(pred, cs, cv, tables)
    return pred, cs, cv, votes, pc


def test_o1_specimen_coverage(model):
    o = model["o"]
    n = len(o["sx"])
    report("O1-specimens", sites=n, cells=int(len(o["bit"])), columns=len(set(o["sx"].tolist())), rows=len(set(o["sy"].tolist())),
           les=len(set(o["le"].tolist())), stray_cells=int(o["stray_cells"]))
    assert len(o["bit"]) == 16 * n and int(o["stray_cells"]) == 0


@pytest.mark.parametrize("colp,rowp,sx,sy", list(itertools.product(["ltr", "rtl"], ["asc", "desc"], [1, -1], [1, -1])))
def test_o1_hypothesis(colp, rowp, sx, sy, model, tables):
    """Set level: the 16 predicted cells of a site equal its 16 observed cells (pin swaps permute INIT bits inside the set)."""
    _, cs, cv, votes, pc = predict(model, colp, rowp, sx, sy, tables)
    ok = M.site_matches(pc, model["oc"])
    report("O1-hyp", col=colp, row=rowp, sx=sx, sy=sy, frame_const=cs, v_const=cv, votes=votes, sites_ok=int(ok.sum()), sites=len(ok))
    if (colp, rowp, sx) == ("ltr", "asc", 1):
        assert ok.all()
    elif not ok.all():
        pytest.xfail(f"{int(ok.sum())}/{len(ok)} sites")


def test_o1_vendor_sign_needs_no_constant(model, tables):
    """sy = +1 (the vendor formula as read) reproduces every site with frame/v constants (0, 0) against the blkrba csv y_cum."""
    _, cs, cv, votes, pc = predict(model, "ltr", "asc", 1, 1, tables)
    assert (cs, cv) == (0, 0)
    assert M.site_matches(pc, model["oc"]).all()


def test_o1_bit_order_is_complement_of_a_pin_swap(model, tables):
    """INIT bit b sits at RBLUT index 15 - sigma(b), sigma = a per-site permutation of the 4 LUT input bits (fitter pin swap)."""
    _, _, _, _, pc = predict(model, "ltr", "asc", 1, 1, tables)
    perm = M.bit_permutations(pc, model["oc"])
    good = sum(M.is_index_bit_permutation(15 - p) for p in perm)
    report("O1-bitorder", sites=len(perm), complement_of_pin_swap=good,
           identity_order=int(sum((p == np.arange(16)).all() for p in perm)))
    assert good == len(perm)


def test_o1_all_cells(model, tables):
    """The 2,396,160 LUT-bit cells of the validated model: distinct, inside the CRAM, equal to the asmdb decode minus its pool offset."""
    m = model
    c, r, le, k = np.meshgrid(*[np.arange(n) for n in (M.COLS, M.ROWS_, M.LES, M.KS)], indexing="ij")
    a = M.addresses(c, r, le, k, m["hi0"], m["lo"], m["dx"], m["dy"], 1, 1).ravel()
    rr, jj, kk = P.sof_to_rbf(a, tables)
    cell = (rr * 800 + jj) * 8 + kk
    inside = int(((a >= 0) & (a < P.N_BITS)).sum())
    report("O1-all", cells=N, in_cram=inside, distinct=len(np.unique(cell)))
    assert a.size == N and inside == N and len(np.unique(cell)) == N
    if os.path.exists(os.path.join(os.path.dirname(M.BODY), "lut_asm_addr.npy")):
        pool = np.load(os.path.join(os.path.dirname(M.BODY), "lut_asm_addr.npy"))
        # the decoded pool vectors carry y_cum + 3; the oracle needs y_cum (see #165)
        assert (pool - a == 3).all()


def test_o1_address_to_plane_is_sof_identity(tables):
    a = np.array([0, 1, 6153, 6154, 39_040_975])
    for x, y in zip(P.address_to_plane(a, tables), P.sof_to_rbf(a, tables)):
        assert (x == y).all()
