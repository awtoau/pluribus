"""Vendor-only checks for the Cyclone V clean PRAM tables (skipped without a Quartus install)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lifters.cyclonev_clean import pram  # noqa: E402

pytestmark = pytest.mark.skipif(not os.environ.get("PLURIBUS_QUARTUS_DEVINFO"), reason="no Quartus devinfo")


@pytest.mark.parametrize("die,total", [("e50f", 51101), ("d6_gtf150", 113922), ("gx25f", 54083)])
def test_extents_tile_cff_space(die, total):
    hdr, rows, own = pram.vendor_tables(die)  # raises on any double claim
    assert hdr["num_cff_bits"] == total
    assert len(own) == total
