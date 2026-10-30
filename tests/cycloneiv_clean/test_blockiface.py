"""routing.ddb block interfaces (#171): pad pin -> BLOCK_INPUT_MUX index from vendor data, checked against the label specimens and GT edges."""
import collections
import glob
import os

import pytest

from conftest import REPO, need, report

BIM_SPEC = os.path.join(REPO, "tmp", "cycloneiv_clean", "bim_specimens")
# source: scripts/cycloneiv_clean_bim_specimens.py labels (routing.rcf BIM of each output pad, 6 builds, 24 / 24 pads): SUB_LOC -> (BIM tile dx, BIM index)
SPECIMEN = {0: (1, 0), 1: (1, 14), 2: (0, 5), 3: (0, 13)}


@pytest.fixture(scope="module")
def pins():
    need(os.path.join(REPO, "tmp", "ddb", "stingray4_routing.bin"))
    from lifters.cycloneiv_clean import blockiface
    return blockiface.Pins()


def test_pool_counts():
    need(os.path.join(REPO, "tmp", "ddb", "stingray4_routing.bin"))
    from lifters.cycloneiv_clean import blockiface
    ifs = blockiface.load()
    c = collections.Counter(d["type"] for d in ifs)
    report("blockiface-pool", interfaces=len(ifs), nodes=sum(len(d["nodes"]) for d in ifs), by_type=dict(c))
    assert len(ifs) == 28 and sum(len(d["nodes"]) for d in ifs) == 983 and c == {0: 6, 1: 22}


def test_vio_data_pin_equals_specimens(pins):
    from lifters.cycloneiv_clean import bim
    got = {k: bim.vio_pin(k) for k in range(4)}
    report("blockiface-vio-data", got=str(got))
    assert got == SPECIMEN


def test_hio_pin_layout(pins):
    """HIO: BLOCK_INPUT_MUX = 8 z + pin offset (DATAIN 5, OE 4); one pad pin per BLOCK_INPUT_MUX, no sharing."""
    assert [pins.bim("HIO", "DATAIN", z) for z in range(4)] == [5, 13, 21, 29]
    assert [pins.bim("HIO", "OE", z) for z in range(4)] == [4, 12, 20, 28]
    vals = [v for k, v in pins.table.items() if k[0] == "HIO"]
    assert len(vals) == len(set(vals)) == 32


def test_li_counts(pins):
    assert pins.li_count("HIOL") == pins.li_count("HIOR") == 42
