"""M9K content map (9,216 mux positions, 9 port widths, 132 specimens at many sites) and control-bit cross-site signatures (#169)."""
import numpy as np

from _hb import score_module
from conftest import report


def test_index_layout_is_injective_per_width():
    from lifters.cycloneiv_clean import m9k
    for w in m9k.WIDTHS:
        wd, bt = np.divmod(np.arange(m9k.depth(w) * w), w)
        pos = m9k.pos_of_index(m9k.index(w, wd, bt))
        assert len(np.unique(pos)) == len(pos) and pos.max() < m9k.CONTENT_BITS
    p = np.arange(m9k.CONTENT_BITS)
    assert (m9k.pos_of_index(m9k.index_of_pos(p)) == p).all()


def test_content_map_matches_specimens():
    m = score_module("gxm9k_b18_k0", "gxm9k_hb16_k0", "gxm9k_r16_s1")
    try:
        rows, tot = m.score_m9k_content()
    except (FileNotFoundError, ImportError) as e:
        import pytest
        pytest.skip(str(e))
    report("hardblocks_m9k_content", specimens=len(rows), **tot)
    assert tot["wrong"] == 0 and tot["missing"] == 0 and tot["extra"] == 0 and len(rows) >= 100


def test_control_signatures_cross_site():
    m = score_module("gxm9k_w_base_o", "gxm9k_w_x65_y40_n0_base_o")
    rows, tot = m.score_m9k_ctl()
    report("hardblocks_m9k_control", pairs=len(rows), **tot)
    assert tot["matched"] >= 40 and tot["wrong"] <= 1
