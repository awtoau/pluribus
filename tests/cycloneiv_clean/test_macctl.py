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
