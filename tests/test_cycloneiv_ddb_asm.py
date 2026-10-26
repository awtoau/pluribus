"""Cyclone IV GX asm.ddb semantics (docs/cycloneiv-ddb-format.md) on synthetic data: no Quartus install needed."""
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_asm_decode as D  # noqa: E402
import cycloneiv_ddb_asm as A  # noqa: E402


def test_group_sizes_last_group_implicit():
    # two records: n=3 vals=[flag,3,3] nb=8 -> groups 3,3,2 ; n=0 nb=0 -> one empty group
    a = {"n": np.array([3, 0]), "nb": np.array([8, 0]), "vals": np.array([1, 3, 3], np.uint16), "voff": np.array([0, 3])}
    gsize, grec, gstart = A.group_sizes(a)
    assert gsize.tolist() == [3, 3, 2, 0]
    assert grec.tolist() == [0, 0, 0, 1]
    assert gstart.tolist() == [0, 3, 6, 8]


def test_asm_to_plane_mirrors_inside_the_lab_column():
    fxs = np.array([100, 135, 170])
    pf, pv = D.asm_to_plane([135 + 7, 135 + 2, 135 + 12], [10, 6344 - 20, 0], fxs)
    assert pf.tolist() == [135 + 10, 135 + 15, 135 + 5]       # offset k -> 17 - k
    assert pv.tolist() == [6334, 20, 6344]                     # v -> 6344 - v


def test_programmed_bits_follow_the_roles():
    b0 = [1, -1, 0, 1, -1, 0, 0, -1, 0]
    b1 = [0, -1, 1, 1, 0, -1, 0, 0, 0]
    first = [True, False, False, True, False, False, True, False, False]
    assert D.programmed(b0, b1).tolist() == [True, True, False, True, False, True, False, False, False]
    assert D.programmed(b0, b1, first).tolist() == [True, True, False, True, False, True, True, False, False]


def test_pos_index():
    ix = A.PosIndex(np.array([5, 3, 5, 9]))
    assert sorted(ix.bits(5).tolist()) == [0, 2]
    assert ix.bits(4).tolist() == []
