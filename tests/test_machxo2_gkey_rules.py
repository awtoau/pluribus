"""gkey() rules derived from Diamond routes (docs/machxo2-diamond-oracle.md).

Each assertion is a fact the vendor oracle confirmed (0 DISAGREE over the corpus):
  * H-span fold at the die edge: wire D seg k at off-die column p == opposite direction, same
    index+segment, at column -1-p (left) / 2*max_col+1-p (right).
  * Secondary network (LCMXO2-1200): VSTX0200/0300 of column g is spine (g+3)%4 (+4); HSBX group
    wires resolve to the HSBX0000/0400 tap at Diamond column A-1.
Needs the trellis database; skips without it.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))


@pytest.fixture(scope="module")
def L():
    try:
        import toolchain
        os.environ.setdefault("TRELLIS_DBROOT", toolchain.trellis_dbroot())
        from lifters import machxo2_lift as ML
        return ML.MachXO2Lift("LCMXO2-1200")
    except Exception as exc:
        pytest.skip(f"trellis routing graph unavailable: {exc}")


def bare(L, row, col, name):
    g = L.rg.globalise_net(row, col, name)
    return (g.loc.x, g.loc.y, g.id)


@pytest.mark.parametrize("col", [0, 1, 2])
def test_left_fold_h06w_sink_is_the_mirrored_h06e(L, col):
    # W3_H06W{i}03 at col c: wire starts at c and runs off the die; it returns as H06E seg3 at 2-c
    assert L.gkey(5, col, "W3_H06W0003") == L._v02_alias(*bare(L, 5, 2 - col, "H06E0003"))


@pytest.mark.parametrize("col", [0, 1, 2])
def test_left_fold_h06e_source_is_the_mirrored_h06w(L, col):
    assert L.gkey(5, col, "W3_H06E0103") == L._v02_alias(*bare(L, 5, 2 - col, "H06W0103"))


def test_right_fold_matches_left_by_symmetry(L):
    mc = L.chip.get_max_col()
    assert L.gkey(5, mc, "E3_H06E0003") == L._v02_alias(*bare(L, 5, mc - 2, "H06W0003"))
    assert L.gkey(5, mc - 2, "E3_H06W0203") == L._v02_alias(*bare(L, 5, mc, "H06E0203"))


def test_fold_keeps_h02_flip(L):
    assert L.gkey(5, 0, "W1_H02W0401") == L._v02_alias(*bare(L, 5, 0, "H02E0401"))


def test_vstx_is_a_center_spine_by_column(L):
    from native_trellis.geometry import CENTER_MAP
    crow, ccol = CENTER_MAP[(L.chip.get_max_row(), L.chip.get_max_col())]
    for col in range(1, 21):
        assert L.gkey(3, col, "G_VSTX0200") == (ccol, crow, f"G_VSRX0{(col + 3) % 4}00")
        assert L.gkey(3, col, "G_VSTX0300") == (ccol, crow, f"G_VSRX0{(col + 3) % 4 + 4}00")


def test_hsbx_group_wires_resolve_to_their_tap(L):
    # Diamond: R3C10_VSTX0200 -> R3C10_HSBX0000 -> R3C11_HSBX0001 -> CE of C9..C12 (graph 8..11)
    tap = (9, 3, "G_HSBX0000")
    assert L.gkey(3, 9, "G_HSBX0000") == tap
    for col in (8, 9, 10, 11):
        assert L.gkey(3, col, "G_HSBX0001") == tap
    # Diamond: R4C11_HSBX0000 -> R4C12_HSBX0101 -> LSR of C10..C13 (graph 9..12)
    tap = (10, 4, "G_HSBX0000")
    for col in (9, 10, 11, 12):
        assert L.gkey(4, col, "G_HSBX0101") == tap
    # Diamond: R4C12_HSBX0000 -> R4C13_HSBX0201 (the other CE track, anchored 2 columns on)
    assert L.gkey(4, 12, "G_HSBX0201") == (11, 4, "G_HSBX0000")


def test_density_prefix_is_stripped_only_for_this_device(L):
    assert L._density_name("1200_S5_JB5") == "S5_JB5"
    assert L._density_name("2000_S6_JB5") is None
    assert L._density_name("W1_JB5") == "W1_JB5"
