"""M9K content position from the vendor writer (map_ram_content@0x275d0) against the specimen-read layouts (#165, #169, ledger M-025)."""
import numpy as np
import pytest

from lifters.cycloneiv_clean import m9k


def _inverse(width, p):
    """mux position -> (physical address, physical row) per the code formula (inverse of eab_position)."""
    p = np.asarray(p, np.int64)
    if width in (1, 2, 4, 8):
        row, col = p // 256, p % 256
        assert (row % 9 != 8).all(), "position in a parity row"
        u = (row - row // 9) * 256 + col
    elif width == 16:
        u = np.where(p >= 0x1200, p - 0x200, p)
    else:
        u = p
    if width in (32, 36):
        return u % 256, u // 256
    return ((u // 256) // width) * 256 + u % 256, (u // 256) % width


@pytest.mark.parametrize("width", [1, 2, 4, 8, 9, 16, 18])
def test_specimen_layouts_are_a_pin_permutation_of_the_code_position(width):
    d = m9k.depth(width)
    w, b = np.repeat(np.arange(d), width), np.tile(np.arange(width), d)
    addr, row = _inverse(width, m9k.pos_of_index(m9k.index(width, w, b)))
    assert (m9k.eab_position(width, addr, row) == m9k.pos_of_index(m9k.index(width, w, b))).all()
    a_of_w = np.zeros(d, np.int64)
    a_of_w[w] = addr
    assert (a_of_w[w] == addr).all(), "physical address must be a function of the word"
    r_of_b = np.zeros(width, np.int64)
    r_of_b[b] = row
    assert (r_of_b[b] == row).all(), "physical row must be a function of the bit"
    assert len(set(a_of_w.tolist())) == d


def test_x36_atom_is_row_times_256_plus_address():
    w = np.repeat(np.arange(256), 36)
    b = np.tile(np.arange(36), 256)
    assert (m9k.eab_position(36, w, b) == b * 256 + w).all()
    assert (m9k.eab_position(36, w, b) == m9k.pos_of_index(w * m9k.ATOM36_STRIDE + b)).all()
    assert m9k.pos_of_index(4608 + 36 * 5 + 7) == m9k.eab_position(36, 128 + 5, 7)       # hl_rom_2: address pin 7 unconnected (high)


def test_parity_rows_are_8_17_26_35_for_narrow_widths():
    pos = m9k.eab_position(1, np.arange(8192), 0)
    assert sorted(set((pos // 256).tolist())) == [r for r in range(36) if r % 9 != 8]


def test_bit_rows_constant_is_the_dirt_value():
    pll = pytest.importorskip("lifters.cycloneiv_clean.pll")
    try:
        nodes, tt = pll._dirt()
    except Exception as e:                      # vendor install absent
        pytest.skip(str(e))
    for n in nodes:
        if n["cls"] == 3 and tt.get(n["idx"]) == "CONST_NUM_EAB_BIT_ROWS":
            assert n["abs"] == m9k.BIT_ROWS
            return
    pytest.fail("CONST_NUM_EAB_BIT_ROWS not in dirt")
