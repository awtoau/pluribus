"""PLL parameters (CFF, absolute addresses) vs the Quartus post-fit netlist of 28 altpll specimens (#169)."""
from _hb import score_module
from conftest import report


def test_pll_params_match_postfit_netlist():
    m = score_module("gxhb_pll_base", "gxhb_pllsite_1")
    try:
        rows, tot = m.score_pll()
    except (FileNotFoundError, ImportError) as e:
        import pytest
        pytest.skip(str(e))
    report("hardblocks_pll", specimens=len(rows), **tot)
    assert len(rows) >= 20 and tot["wrong"] == 0 and tot["missing"] == 0 and tot["extra"] == 0 and tot["matched"] >= 8 * len(rows)


def test_pll_site_table_is_enable_bit():
    from lifters.cycloneiv_clean import pll
    assert pll.PLL_SITE[1] == (43, 0) and len(set(pll.PLL_SITE.values())) == len(pll.PLL_SITE)
