"""macctl.py: MAC used / sign / registers / nine-bit / pins against the post-fit netlist of the gxhb_mac* specimens (#165)."""
import os
import sys

import pytest

from conftest import REPO, need, report

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")


@pytest.fixture(scope="module")
def cx():
    need(os.path.join(CORPUS, "gxhb_macpa_base", "bitstream.rbf"))
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    from lifters.cycloneiv_clean import emit
    return emit.Ctx()


def test_mac_specimens_zero_faults(cx):
    import cycloneiv_clean_mac_check as C
    names = [n for n in sorted(os.listdir(CORPUS)) if n.startswith("gxhb_mac") and n != "gxhb_mac_two_mult_w9"]
    tot = {c: C.counts() for c in C.CATS}
    for n in names:
        r = C.score_design(cx, os.path.join(CORPUS, n), 2)
        for c in C.CATS:
            for k, v in r["cats"][c].items():
                tot[c][k] += v
    report("macctl", **tot)
    for c, v in tot.items():
        assert v["missing"] == v["extra"] == v["wrong"] == 0, (c, v)
    assert tot["mac_cfg"]["matched"] > 100 and tot["mac_pin"]["matched"] > 1000
