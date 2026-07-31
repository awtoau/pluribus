"""Recovered output pads must land on their driver's net (#46).

WHY THIS EXISTS
---------------
Two changes shipped that each broke MachXO2 net merging chip-wide, taking the
corpus equivalence sweep from 444/454 to 11/463.  The whole unit-test suite
passed throughout, because every test was a pure function test -- LUT INIT
decoding, DSU algebra, enum correction -- and nothing joined `.config` text to
the routing graph to a recovered net.  The break was only visible by building
bitstreams and running yosys, which takes minutes and needs Diamond.

These tests close that gap with committed `.config` fixtures: no Diamond, no
bitstream decode, no yosys, ~1s.  They assert the ONE invariant both defects
violated -- an output pad and the FF/LUT that drives it must resolve to the
SAME recovered net -- on each chip edge, since the second defect hit only the
bottom edge (5/350 passing there while left/right scored 18/18).

The fixtures are decoder output for real Diamond builds:
    machxo2_toggle_pin36_bottom  re_iostd_*   toggle FF -> bottom-edge pad
    machxo2_toggle_pin45_bottom  re_edge_pin45  ditto, different bottom column
    machxo2_toggle_pin2_left     re_edge_pin2   toggle FF -> left-edge pad
    machxo2_regbuf_pin84_top     lut4_buf_a     registered buffer -> top-edge pad

They need the trellis database (routing graph); the tests skip without it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
DEVICE = "LCMXO2-1200"
PACKAGE = "TQFP100"

# (fixture, output pin, edge) -- pin numbers are TQFP100 package pins.
CASES = [
    ("machxo2_toggle_pin36_bottom.config", "36", "bottom"),
    ("machxo2_toggle_pin45_bottom.config", "45", "bottom"),
    ("machxo2_toggle_pin2_left.config", "2", "left"),
    ("machxo2_regbuf_pin84_top.config", "84", "top"),
]

# Pin 45 was carried here as a strict xfail while bottom-edge pads (45, 85, 86)
# still stranded their output net.  The vertical-span canonicalisation fix made
# it XPASS, which is precisely what the strict marker was for -- it reported the
# gap closing instead of the case being quietly deleted.  Kept as a live case.
KNOWN_UNMERGED_PINS = set()


def _maybe_xfail(pin):
    if pin in KNOWN_UNMERGED_PINS:
        return pytest.mark.xfail(strict=True, reason="known net-merge gap")
    return ()


def _lift():
    """Shared lifter, or skip when the trellis database is unavailable."""
    try:
        import toolchain
        os.environ.setdefault("TRELLIS_DBROOT", toolchain.trellis_dbroot())
        from lifters import machxo2_lift as ML
        return ML, ML.MachXO2Lift(DEVICE)
    except Exception as exc:            # no database / no routing graph here
        pytest.skip(f"trellis routing graph unavailable: {exc}")


@pytest.fixture(scope="module")
def lift():
    return _lift()


@pytest.mark.parametrize(
    "fixture,pin,edge",
    [pytest.param(*c, marks=_maybe_xfail(c[1])) for c in CASES],
    ids=[c[2] + "_pin" + c[1] for c in CASES])
def test_output_pad_shares_its_drivers_net(lift, fixture, pin, edge):
    """The pad's recovered net IS the net some LUT Z or FF Q drives.

    Both #46 defects showed up here and nowhere else: the fabric logic lifted
    perfectly while the pad sat alone on a net of its own, so the recovered
    design had an output nothing drove.
    """
    ML, L = lift
    path = os.path.join(FIXTURES, fixture)
    design = L.recover_netlist(L.parse_config(path))

    site = ML.load_iodb(DEVICE)["packages"][PACKAGE][pin]
    pad = ML.pad_net(design, L, site["row"], site["col"], site["pio"], "out")
    assert pad is not None, f"{edge} pin {pin}: output pad resolved to no net"

    driven = {lt["z"] for lt in design.luts if lt["z"]}
    driven |= {ff["q"] for ff in design.ffs if ff["q"]}
    assert pad in driven, (
        f"{edge} pin {pin}: pad net {pad!r} has no driver -- net merge is "
        f"broken. Driven nets: LUT z={sorted(lt['z'] for lt in design.luts if lt['z'])} "
        f"FF q={sorted(ff['q'] for ff in design.ffs if ff['q'])}")


@pytest.mark.parametrize("fixture,pin,edge", CASES,
                         ids=[c[2] + "_pin" + c[1] for c in CASES])
def test_input_pad_reaches_the_fabric(lift, fixture, pin, edge):
    """The clock pad (pin 88 in every fixture) must resolve to a net that some
    recovered cell actually consumes -- the input-side mirror of the above."""
    ML, L = lift
    design = L.recover_netlist(L.parse_config(os.path.join(FIXTURES, fixture)))
    site = ML.load_iodb(DEVICE)["packages"][PACKAGE]["88"]
    net = ML.pad_net(design, L, site["row"], site["col"], site["pio"], "in")
    assert net is not None, f"{edge} fixture: clock pad 88 resolved to no net"
    consumed = set()
    for lt in design.luts:
        consumed |= {lt[p] for p in "abcd" if lt[p]}
    for ff in design.ffs:
        consumed |= {ff[k] for k in ("d", "clk", "ce", "lsr") if ff[k]}
    assert net in consumed, (
        f"{edge} fixture: clock pad net {net!r} is consumed by nothing")


def test_tile_coords_come_from_the_routing_graph(lift):
    """tile_rc, not the text of the tile name, decides where a tile is.

    Trellis names number columns from 1 and routing-graph positions from 0, so
    reading R/C out of "R2C12:PLC" puts it one column right of where it is.
    Doing that desynchronised PLC internals from the surrounding CIB routing and
    cost 438 corpus targets their equivalence proof.
    """
    _ML, L = lift
    assert L.tile_rc["R2C12:PLC"] == (2, 11)
    assert L.tile_rc["CIB_R1C12:CIB_PIC_T0"] == (1, 11)


def test_v02s_alias_agrees_across_reference_forms(lift):
    """One physical wire, one canonical key -- however it is named.

    A bare "V02S0701" is rewritten to its V02N mate before globalising, while a
    hop-prefixed "S1_V02S0701" reaches the same wire through globalise_net.  The
    two paths MUST agree; when they did not, every bottom-edge output pad was
    stranded on its own net.
    """
    _ML, L = lift
    assert L.gkey(11, 10, "V02S0701") == L.gkey(10, 10, "S1_V02S0701")
