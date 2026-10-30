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


def test_code_derived_writer_rules():
    """libcomp_asmram writer rules (REG_DATA_OUT, NEW_DATA_MODE; one-hot select; stored as written) vs gxm9k_w_* builds."""
    m = score_module("gxm9k_w_base_o", "gxm9k_w_rdw_old")
    rows, tot = m.score_m9k_code_rules()
    report("hardblocks_m9k_code_rules", builds=len(rows), **tot)
    assert tot["wrong"] == 0 and tot["missing"] == 0 and tot["matched"] >= 90


def _walk():
    import pytest
    from lifters.cycloneiv_clean import asmdb_walk as W, sofio
    try:
        return W.Walk()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))


def test_select_semantics_against_specimens():
    walk = _walk()
    """Vendor mux select code: M9K RAM_USAGE_MODE maps usage 0,1,2 to the same 17-bit pattern (0x1ff81); REG_DATA_OUT value 1 clears its cell."""
    import numpy as np
    from lifters.cycloneiv_clean import asmdb_select as S
    ref = next(g["paths"][0][0] for g in walk.groups() if g["btype"] == 39 and g["cls"] == 5 and len(walk.mux(g["paths"][0][0])["bits"]) == 17)
    pats = [dict(S.select(walk, ref, v)) for v in (0, 1, 2)]
    assert pats[0] == pats[1] == pats[2]
    assert sum(pats[0].values()) == 11 and [pats[0][b] for b in list(pats[0])[:1]] == [1]
    assert int(sum(x << i for i, (_, x) in enumerate(S.select(walk, ref, 0)))) == 0x1FF81
    import pytest
    with pytest.raises(ValueError):
        S.select(walk, ref, 3)


def test_mode_groups_from_writer_rules():
    """TRUE_DUAL_PORT_MODE / PACKED_MODE from the libcomp_asmram writer rules over flag names, vs 4 altsyncram mode builds and 9 width builds."""
    m = score_module("gxm9k_m_base_s", "gxm9k_hb16_base")
    rows, tot = m.score_m9k_modes()
    report("hardblocks_m9k_modes", builds=len(rows), **tot)
    assert tot["wrong"] == 0 and tot["missing"] == 0 and tot["matched"] >= 24
