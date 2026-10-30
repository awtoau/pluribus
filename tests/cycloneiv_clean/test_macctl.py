"""macctl.py: MAC used / sign / registers / nine-bit / pins against the post-fit netlist of the gxhb_mac* specimens (#165)."""
import os
import sys

import pytest

from conftest import REPO, need, report

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")


@pytest.fixture(scope="module")
def cx():
    need(os.path.join(CORPUS, "gxhb_mac_dyn_signa", "bitstream.rbf"))
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    from lifters.cycloneiv_clean import emit
    return emit.Ctx()


def test_mac_specimens_zero_faults(cx):
    import cycloneiv_clean_mac_check as C
    names = [n for n in sorted(os.listdir(CORPUS)) if n.startswith("gxhb_mac")]
    tot = {c: C.counts() for c in C.CATS}
    for n in names:
        r = C.score_design(cx, os.path.join(CORPUS, n), 2)
        for c in C.CATS:
            for k, v in r["cats"][c].items():
                tot[c][k] += v
    report("macctl", **tot)
    for c, v in tot.items():
        assert v["missing"] == v["extra"] == v["wrong"] == 0, (c, v)
    assert tot["mac_cfg"]["matched"] > 100 and tot["mac_pin"]["matched"] > 500


def test_nine_bit_rows():
    from lifters.cycloneiv_clean import macctl
    # source: GT routes of gxhb_mac_two_mult_w9 (N0 = mac_mult7, N1 = mac_mult5): row k -> DATAA / DATAB pin
    assert macctl.rows(0, True) == (list(range(0, 9)), list(range(18, 27)))
    assert macctl.rows(1, True) == (list(range(9, 18)), list(range(27, 36)))
    assert macctl.rows(0, False) == (list(range(18)), list(range(18, 36)))


def test_macx_pairs_decode(cx):
    """ledger MA-004: one-feature pairs (scripts/cycloneiv_clean_hardblocks_build.py set macx) decode to the expected control values."""
    import numpy as np
    from lifters.cycloneiv_clean import tracer as T

    def dec(n):
        rbf = os.path.join(CORPUS, n, "bitstream.rbf")
        need(rbf)
        md = cx.macctl.decode(T.plane_bits(rbf))
        i = int(np.flatnonzero(md["used"])[0])
        return {k: (v[i] if getattr(v, "ndim", 0) else v) for k, v in md.items()}
    d = {n: dec("gxhb_macx_" + n) for n in ("base0", "clkinv", "ena", "enainv", "aclr", "aclrinv", "aclrloc", "dynsab", "sregab", "sregb", "plain", "invda", "invdb")}
    assert not d["base0"]["clk_inv"] and d["clkinv"]["clk_inv"]                      # MAC_CLK_INVERT
    assert not d["ena"]["ena_inv"] and d["enainv"]["ena_inv"]                         # MAC_CE_INVERT (set = inverted)
    assert not d["aclr"]["aclr_inv"] and d["aclrinv"]["aclr_inv"]                     # MAC_CLR_INVERT (cleared = inverted)
    assert d["aclr"]["clr_line"] >= 0 and d["aclr"]["aclr_sel"] < 0                   # global clear: MAC_CLR_FAST_MUX line
    assert d["aclrloc"]["clr_line"] < 0 and d["aclrloc"]["aclr_sel"] >= 0             # local clear: MAC_PIA_TO_CLR
    assert d["ena"]["ena_sel"] >= 0
    assert list(d["sregab"]["sreg"]) == [True, True] and list(d["sregb"]["sreg"]) == [False, True] and not d["dynsab"]["sreg"].any()   # MAC_IREG_SIGN gi 0 / 1
    assert d["invda"]["data_inv"][:18].all() and not d["invda"]["data_inv"][18:].any()
    assert d["invdb"]["data_inv"][18:].all() and not d["invdb"]["data_inv"][:18].any() and not d["plain"]["data_inv"].any()
    b, o, m = dec("gxhb_mac_two_mult_w9"), dec("gxhb_mac_two_in_reg"), dec("gxhb_mac_two_mult_reg")
    assert not b["ireg_n"][1].any() and o["ireg_n"][1].all()                          # N1 input registers: IREG_UPPER
    assert not b["oreg_n"][1] and m["oreg_n"][1]                                      # N1 output register: OREG gi 1
