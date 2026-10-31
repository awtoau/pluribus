"""ffctl.py: FF control decode (enable, async clear, sync clear / load, clock polarity, ASDATA) and carry-in against the post-fit netlist (#165).

Designs: register-control corpus (ffc_000, ffc_001), a LAB_CONTROL_MUX-clocked design (gxct_a_idle_ff15), a sload-tied-high design (sp_087),
an inverted enable / sload design (rb_010).  Zero missing / extra / wrong per construct; matched counts reported to the oracle log.
"""
import os
import sys

import pytest

from conftest import REPO, need, report

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
DESIGNS = ("gx150_ffc_000", "gx150_ffc_001", "gx150_rb_010", "gxct_a_idle_ff15", "gx150_sp_087",
           "gxct_e_regfb_sload")  # register feedback + independent ASDATA on one LE (#183, F-021)


@pytest.fixture(scope="module")
def cx():
    need(*(os.path.join(CORPUS, d, "bitstream.rbf") for d in DESIGNS))
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    from lifters.cycloneiv_clean import emit, tracer as T
    c = emit.Ctx()
    c.res = T.Resolver(c.rt)
    c.st.edge_ids([0], [0])
    return c


def test_ff_controls_match_postfit(cx):
    import cycloneiv_clean_ffctl_check as C
    tot = {k: {"matched": 0, "missing": 0, "extra": 0, "wrong": 0} for k in C.CATS}
    for d in DESIGNS:
        r = C.score_design(cx, os.path.join(CORPUS, d), 2)
        for k in C.CATS:
            for f in tot[k]:
                tot[k][f] += r["cats"][k][f]
    report("ffctl", **{k: v for k, v in tot.items()})
    for k, v in tot.items():
        assert v["missing"] == v["extra"] == v["wrong"] == 0, (k, v)
    assert tot["ff_clk_pol"]["matched"] > 0 and tot["ff_aclr"]["matched"] > 0 and tot["ff_sload"]["matched"] > 0


def test_value_law_inverts_arch_value_zero(cx):
    """LE_CLOCK_SELECT / LE_CLEAR_SELECT / LAB_ENABLE_CE / LE_USE_CARRY carry arch_value 0: vendor value = NOT bit."""
    import numpy as np
    fc = cx.ffc
    assert all(av == 0 for n, (c, av) in fc.le.items() if n in ("LE_CLOCK_SELECT", "LE_CLEAR_SELECT", "LE_USE_CARRY"))
    assert all(av == 1 for n, (c, av) in fc.le.items() if n in ("LE_USE_SYNC_CLEAR", "LE_USE_SYNC_LOAD", "LE_USE_REGISTER_FEEDBACK"))
    bits = np.zeros(int(max(c.max() for c, _ in fc.le.values())) + 1, np.uint8)
    v = fc.le_val(bits)
    assert (v["LE_CLOCK_SELECT"] == 1).all() and (v["LE_USE_SYNC_CLEAR"] == 0).all()
