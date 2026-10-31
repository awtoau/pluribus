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


def _need_quartus():
    import pytest
    try:
        from lifters.cycloneiv_clean import pll
        pll.pll_tiles()
    except (FileNotFoundError, ImportError, StopIteration) as e:
        pytest.skip(str(e))


def test_pll_sites_derived_from_dirt_coordinate_map():
    """PLL_k = IC_DESIGN_INDEX of the dirt COORDINATE_MAP_DATA; the six specimen-measured paths agree, PLL_6 / PLL_7 are FAST_PLL paths 2 / 3 (#175)."""
    _need_quartus()
    from lifters.cycloneiv_clean import pll
    s = pll.PLL_SITE
    assert {k: s[k] for k in (1, 2, 3, 4, 5, 8)} == {1: (43, 0), 2: (43, 5), 3: (45, 0), 4: (45, 1), 5: (43, 1), 8: (43, 4)}
    assert s[6] == (43, 2) and s[7] == (43, 3) and sorted(s) == list(range(1, 9))
    assert pll.pll_tiles()[1][2] == (0, 13) and pll.pll_tiles()[3][2] == (117, 1)


def test_clock_buffer_tiles_derived_from_dirt_runs():
    """30 clock buffer sites = 5 runs of 6 in CLKMUX_PLL_SOURCE; each run resolves to one tile by its PLL parents (replaces the hand-typed list)."""
    _need_quartus()
    import numpy as np
    from lifters.cycloneiv_clean import clkbuf, ddb, pll
    rt = ddb.Routing()
    enum = np.where(rt.tpl >= 0, rt.enum[np.maximum(rt.tpl, 0)].astype(np.int32), -1)
    t = clkbuf.tiles(rt, enum)
    assert t[::6] == [(0, 45), (0, 46), (117, 46), (57, 91), (57, 0)] and len(t) == 30 and all(t[i] == t[i - i % 6] for i in range(30))
    src = pll.clkmux_pll_source()
    assert [src[g] for g in range(0, 30, 6)] == [1, 8, 4, 2, 3]


def test_clkin_source_traced_in_emit_not_just_the_standalone_tracer():
    """emit.Builder._hard reports PLL_CLKIN source via pll.clkin_source (#181 point 2): both enabled PLLs on the DJI image resolve to
    ball B14 (ledger P-011/P-014/P-015), and the netlist's own undecoded count for this cause is 0, not unconditionally len(nl.pll)."""
    import os
    import pytest
    image = os.environ.get("PLURIBUS_DJI_IMAGE", "")
    if not image or not os.path.isfile(image):
        pytest.skip("PLURIBUS_DJI_IMAGE not set or file absent")
    import sys
    from conftest import REPO
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import cycloneiv_clean_image as IMG
    from lifters.cycloneiv_clean import emit
    rbf, _, _ = IMG.container(open(image, "rb").read())
    open(IMG.PLANE, "wb").write(rbf)
    try:
        nl = emit.Builder(emit.Ctx(), IMG.PLANE, "dji_pll_test").run()
    finally:
        os.remove(IMG.PLANE)
    assert {p["k"] for p in nl.pll} == {2, 8}
    assert all(p.get("clkin_ball") == "B14" for p in nl.pll), nl.pll
    assert nl.und.get("PLL: input clock source", 0) == 0


def test_fin_interval_formula_contains_actual_inputs():
    """Fout = Fin * M / (N * C), VCO = Fin * M * post / N: Fin of every altpll build (20 / 25 / 50 MHz) lies in the interval from the vendor limits."""
    _need_quartus()
    import os
    import re
    from conftest import REPO
    from lifters.cycloneiv_clean import pll
    corpus = os.path.join(REPO, "corpus", "cycloneiv")
    names = [n for n in (os.listdir(corpus) if os.path.isdir(corpus) else []) if n.startswith("gxhb_pllsite_")]
    if len(names) < 4:
        import pytest
        pytest.skip("local data missing: corpus/cycloneiv/gxhb_pllsite_*")
    from lifters.cycloneiv_clean import asmdb_walk as W
    import cycloneiv_clean_dirt as D
    pm = pll.load(W.Walk(), D.enum_tables())
    for n in names:
        t = open(os.path.join(corpus, n, "postfit.vo")).read()
        fin = 1e6 / int(re.search(r"inclk0_input_frequency = (\d+)", t)[1])          # ps -> MHz
        cff = pll.read_cff(os.path.join(corpus, n, "bitstream.rbf"))
        (k, bt, p), = pm.used(cff)
        prm = pm.params(cff, bt, p)
        lo, hi = pll.fin_interval(prm, "GPLL")
        assert lo <= fin <= hi, n
        c = prm["c0"]
        assert abs(fin * prm["m"] / (prm["n"] * (c[1] + c[2])) - 100) < 1e-9, n         # clk0_multiply_by 2 on a 50 MHz input: 100 MHz out
