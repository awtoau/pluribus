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


def test_bandwidth_table_predicts_loop_filter():
    from lifters.cycloneiv_clean import pll
    try:
        rows = pll.bandwidth_rows()
    except (FileNotFoundError, ImportError) as e:
        import pytest
        pytest.skip(str(e))
    assert len(rows) == 10 and pll.bandwidth_settings(16, 2) == (1, 27, 0) and pll.bandwidth_settings(112, 2) == (1, 8, 0) and pll.bandwidth_settings(10, 2, 'high') == (3, 27, 0)


def test_bandwidth_tables_reproduce_all_builds():
    """M * post -> (ICP, R, C) from the two vendor text tables vs the netlist of every altpll build (28 of 28)."""
    import os
    import re
    from conftest import REPO
    from lifters.cycloneiv_clean import pll
    corpus = os.path.join(REPO, "corpus", "cycloneiv")
    names = [n for n in (os.listdir(corpus) if os.path.isdir(corpus) else []) if n.startswith("gxhb_pll") and os.path.exists(os.path.join(corpus, n, "postfit.vo"))]
    if len(names) < 20:
        import pytest
        pytest.skip("local data missing: corpus/cycloneiv/gxhb_pll*")
    ok = 0
    for n in names:
        t = open(os.path.join(corpus, n, "postfit.vo")).read()
        g = lambda k: re.search(r"pll1 \." + k + r" = \"?([^\";]*)", t)      # noqa: E731
        if not g("m"):
            continue
        want = (int(g("charge_pump_current_bits")[1]), int(g("loop_filter_r_bits")[1]), int(g("loop_filter_c_bits")[1]))
        assert pll.bandwidth_settings(int(g("m")[1]), int(g("vco_post_scale")[1]), g("bandwidth_type")[1]) == want, n
        ok += 1
    assert ok >= 20
