"""ECP5 clock-tree node identity and CCU2 alias arcs (#116).

No routing graph is built: clock_key() needs only device-db/ECP5/<dev>/globals.json.
Positions come from the 25F Diamond oracle routes (docs/ecp5-diamond-oracle.md).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import toolchain  # noqa: E402
from lifters.ecp5_lift import ECP5Lift  # noqa: E402
from lifters.machxo2_lift import ParsedConfig  # noqa: E402


def lifter():
    L = ECP5Lift.__new__(ECP5Lift)
    L.device = "LFE5U-25F"
    L._dbroot = toolchain.trellis_dbroot()
    return L


def test_quadrant_pclk_is_the_quadrant_hprx():
    L = lifter()
    # Diamond: R31C31_LRPCLK0 -> R37C45_HPRX0000 (same wire, two names)
    assert L.clock_key(31, 31, "G_LRPCLK0") == L.clock_key(37, 45, "G_HPRX0000")
    assert L.clock_key(37, 21, "G_HPRX0000") != L.clock_key(37, 21, "G_HPRX0400")
    assert L.clock_key(13, 31, "G_ULPCLK0") != L.clock_key(31, 31, "G_LLPCLK0")


def test_vptx_spine_and_tap_agree():
    L = lifter()
    # EBR_SPINE_LR1 R37C59 and TAP_DRIVE R38C60 name one vertical wire; Diamond: R38C59_VPTX0000
    k = L.clock_key(37, 59, "G_VPTX0000")
    assert k == L.clock_key(38, 60, "G_VPTX0000") == L.clock_key(38, 59, "G_VPTX0000")
    assert k != L.clock_key(37, 41, "G_VPTX0000")      # other spine of the same quadrant
    assert k != L.clock_key(13, 59, "G_VPTX0000")      # upper half


def test_hpbx_tap_side_and_row():
    L = lifter()
    k = L.clock_key(38, 60, "R_HPBX0000")              # tap tile, right side
    assert k == L.clock_key(38, 67, "G_HPBX0000") == L.clock_key(38, 65, "G_HPBX0000")
    assert k != L.clock_key(38, 55, "G_HPBX0000")      # left side of the same tap
    assert k != L.clock_key(39, 67, "G_HPBX0000")      # HPBX is row-local
    assert L.clock_key(38, 55, "G_HPBX0000") == L.clock_key(38, 60, "L_HPBX0000")


def test_unique_names_and_unmodelled():
    L = lifter()
    assert L.clock_key(0, 31, "G_TDCC2CLKI") == L.clock_key(1, 31, "G_TDCC2CLKI")
    assert L.clock_key(0, 31, "G_JPCLKT00") != L.clock_key(0, 31, "G_JPCLKT01")
    assert L.clock_key(5, 5, "G_DCS0CLK0") is None     # DCS: no Diamond evidence, stays dropped
    assert L.clock_key(5, 5, "E1_H02E0001") is None


def test_ccu2_alias_arcs_dropped_logic_wide_mux_kept():
    pc = ParsedConfig()
    pc.slice_enum[(5, 5, "A")]["MODE"] = "CCU2"
    pc.slice_enum[(5, 5, "B")]["MODE"] = "LOGIC"
    pc.arcs = [(5, 5, "F0", "F5A_SLICE"), (5, 5, "F1", "FXA_SLICE"),
               (5, 5, "F2", "F5B_SLICE"), (5, 5, "A0", "V00B0000")]
    dropped = ECP5Lift._drop_ccu2_alias_arcs(pc)
    assert len(dropped) == 2
    assert pc.arcs == [(5, 5, "F2", "F5B_SLICE"), (5, 5, "A0", "V00B0000")]
