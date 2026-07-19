"""Regression tests for issue #69 — GOWIN decode gaps.

Three independent bugs, all of which silently LOST real design content:

  1. BSRAM ports dropped.  apycula's parse_tile_() returns the placed site name
     ("BSRAM0"), the static tile db keys it "BSRAM"; the KeyError was swallowed
     and the block was emitted with zero ports, so a design with four populated
     memories reported "0 EBR blocks".
  2. Corner IOBs unresolved.  loc2pin_name() names a corner tile on its TOP or
     BOTTOM edge, but the packaged pinout tables name the same pads on the
     LEFT/RIGHT edge, so corner pads never matched and dropped out of pad_map.
  3. Board package.  Chosen from IOB *site* count, which proves nothing.

The unpacker half (1 + 2) is pure name arithmetic over stub objects, so these
tests need neither apycula nor a bitstream.  The lifter half is driven from a
hand-built .gwconfig, as in tests/test_gowin_lift.py.

Run with:  python3 -m pytest tests/test_gowin_issue69.py -v
"""

import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lifters.gowin_lift import GowinLift, _bsram_role     # noqa: E402


def _load_unpack():
    """Import scripts/gowin_unpack.py (module-level imports are stdlib-only)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "scripts", "gowin_unpack.py")
    spec = importlib.util.spec_from_file_location("gowin_unpack_t", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gu = _load_unpack()


# ---------------------------------------------------------------- stubs -----
class _Bel:
    def __init__(self, portmap):
        self.portmap = portmap


class _Tile:
    def __init__(self, bels):
        self.bels = bels


class _DB:
    """Minimal stand-in for an apycula chipdb: grid size + per-tile bels."""

    def __init__(self, rows, cols, tiles):
        self.rows = rows
        self.cols = cols
        self._tiles = tiles

    def __getitem__(self, rc):
        return self._tiles[rc]


# ================================================================ gap 1 ======
# Placed-site-name normalization + fail-fast on a genuine miss.

def test_indexed_site_name_falls_back_to_base_key():
    """BSRAM0 / BSRAM_AUX1 must resolve to the static BSRAM / BSRAM_AUX keys."""
    db = _DB(10, 10, {
        (9, 1): _Tile({"BSRAM": _Bel({"CLKA": "wA", "DIA0": "wB"})}),
        (9, 2): _Tile({"BSRAM_AUX": _Bel({})}),
    })
    assert gu.static_portmap(db, 9, 1, "BSRAM0") == {"CLKA": "wA", "DIA0": "wB"}
    assert gu.static_portmap(db, 9, 1, "BSRAM3") == {"CLKA": "wA", "DIA0": "wB"}
    assert gu.static_portmap(db, 9, 2, "BSRAM_AUX1") == {}


def test_exact_name_wins_over_suffix_strip():
    """LUT0/DFF3/ALU5/BANK2 keep their index — the strip is a fallback only."""
    db = _DB(10, 10, {
        (1, 1): _Tile({
            "LUT0": _Bel({"F": "f0"}),
            "LUT":  _Bel({"F": "WRONG"}),   # decoy base key
        }),
    })
    assert gu.static_portmap(db, 1, 1, "LUT0") == {"F": "f0"}


def test_portmap_miss_is_fatal_not_empty():
    """A genuine lookup miss must die(), never degrade to an empty record.

    The silent degradation is precisely what hid ~210 dropped ports per BSRAM.
    """
    db = _DB(10, 10, {(4, 4): _Tile({"LUT0": _Bel({})})})
    with pytest.raises(SystemExit):
        gu.static_portmap(db, 4, 4, "DSP0")


def test_flatten_port_scalar_vector_and_nested():
    """No portmap wire may be dropped — vectors flatten, nested vectors too."""
    assert list(gu.flatten_port("CLK", "w0")) == [("CLK", "w0")]
    assert list(gu.flatten_port("DI", ["a", "b"])) == [("DI0", "a"), ("DI1", "b")]
    # RAM16.RAD shape: a vector of vectors
    nested = list(gu.flatten_port("RAD", [["a0", "a1"], ["b0", "b1"]]))
    assert nested == [("RAD0_0", "a0"), ("RAD0_1", "a1"),
                      ("RAD1_0", "b0"), ("RAD1_1", "b1")]
    assert len({n for n, _ in nested}) == 4      # names stay unique


# ================================================================ gap 2 ======
# Corner IOB location naming.

@pytest.fixture
def grid():
    """A 19x20 grid the size of GW1N-2 (corners at the four extremes)."""
    return _DB(19, 20, {})


def test_corner_alt_loc_only_fires_on_corners(grid):
    # four corners -> the LEFT/RIGHT-edge name, indexed by ROW
    assert gu.corner_alt_loc(grid, 0, 0) == "IOL1"
    assert gu.corner_alt_loc(grid, 0, 19) == "IOR1"
    assert gu.corner_alt_loc(grid, 18, 0) == "IOL19"
    assert gu.corner_alt_loc(grid, 18, 19) == "IOR19"
    # edge-but-not-corner tiles have exactly one name
    for rc in [(0, 5), (18, 5), (5, 0), (5, 19), (7, 8)]:
        assert gu.corner_alt_loc(grid, *rc) is None


def test_corner_iob_prefers_the_bonded_candidate(grid, monkeypatch):
    """(0,19): loc2pin_name says IOT20; QFN48X bonds it as IOR1."""
    _stub_loc2pin(monkeypatch, {(0, 19): "IOT20", (18, 19): "IOB20"})
    qfn48x = {"IOR1A": 36, "IOR1B": 35}
    assert gu.iob_loc_name(grid, 0, 19, "A", qfn48x) == "IOR1A"
    assert gu.iob_loc_name(grid, 0, 19, "B", qfn48x) == "IOR1B"
    # the same corner under LQFP100, which instead bonds the (18,19) corner
    lqfp100 = {"IOR19A": 7, "IOR19B": 8}
    assert gu.iob_loc_name(grid, 18, 19, "A", lqfp100) == "IOR19A"


def test_unbonded_corner_still_gets_the_lr_name(grid, monkeypatch):
    """With neither candidate bonded, keep the L/R name the pinouts use.

    Otherwise apycula's T/B-biased loc2pin_name leaks into pad_map and the same
    physical pad carries a different label depending on the package.
    """
    _stub_loc2pin(monkeypatch, {(0, 19): "IOT20"})
    assert gu.iob_loc_name(grid, 0, 19, "B", {}) == "IOR1B"


def test_non_corner_iob_name_is_untouched(grid, monkeypatch):
    """The fix must not perturb ordinary edge IOBs."""
    _stub_loc2pin(monkeypatch, {(5, 0): "IOL6", (0, 5): "IOT6"})
    assert gu.iob_loc_name(grid, 5, 0, "A", {"IOL6A": 3}) == "IOL6A"
    assert gu.iob_loc_name(grid, 0, 5, "B", {}) == "IOT6B"


def _stub_loc2pin(monkeypatch, table):
    """Install a fake apycula.chipdb whose loc2pin_name reads TABLE."""
    import types
    fake = types.ModuleType("apycula.chipdb")
    fake.loc2pin_name = lambda db, r, c: table[(r, c)]
    pkg = types.ModuleType("apycula")
    pkg.chipdb = fake
    monkeypatch.setitem(sys.modules, "apycula", pkg)
    monkeypatch.setitem(sys.modules, "apycula.chipdb", fake)


# ================================================================ lifter =====
# BSRAM hardip records -> Design.ebrs -> ebr_ports rows.

BSRAM_GWCONFIG = """\
.device GW1N-2
.tile 9 1 25
lut 9 1 LUT0 1000000000000000 A=nA B=nB C=nC D=nD F=nF
arc 9 1 nA nSRC
arc 9 1 nDIA0 nWDATA
arc 9 1 nDOA0 nRDATA
arc 9 1 nCLKA nCLK
hardip 9 1 BSRAM bel=BSRAM0 CLKA=nCLKA CEA=nCEA WREA=nWREA \
DIA0=nDIA0 DIA1=nDIA1 DOA0=nDOA0 ADA0=nADA0 BLKSELA0=nBLK RESETA=nRST
hardip 9 2 BSRAM_AUX bel=BSRAM_AUX0
"""


@pytest.fixture
def bsram_cfg(tmp_path):
    p = tmp_path / "bsram.gwconfig"
    p.write_text(BSRAM_GWCONFIG)
    return str(p)


def test_bsram_role_classification():
    assert _bsram_role("DOA0") == "read"
    assert _bsram_role("DO17") == "read"
    assert _bsram_role("DIB3") == "write"
    assert _bsram_role("WREA") == "write"
    for ctrl in ("CLKA", "CEB", "OCEA", "RESETB", "ADA13", "BLKSEL2"):
        assert _bsram_role(ctrl) == "ctrl", ctrl


def test_bsram_ports_reach_the_design(bsram_cfg):
    """The whole point of #69: a populated BSRAM must not report zero ports."""
    lift = GowinLift("GW1N-2")
    pc = lift.parse_config(bsram_cfg)
    d = lift.recover_netlist(pc)

    assert len(d.ebrs) == 1, "BSRAM_AUX must not be counted as a memory block"
    blk = d.ebrs[0]
    assert blk["block"] == "R10C2"          # 0-based (9,1) -> 1-based R10C2
    assert len(blk["ports"]) == 9

    by_port = {p["port"]: p for p in blk["ports"]}
    assert by_port["DOA0"]["role"] == "read"
    assert by_port["DIA0"]["role"] == "write"
    assert by_port["CLKA"]["role"] == "ctrl"
    # routed ports resolve to a real net; unrouted ones stay None
    assert by_port["DIA0"]["net"] is not None
    assert by_port["CLKA"]["net"] is not None
    assert by_port["DIA1"]["net"] is None
    assert by_port["ADA0"]["net"] is None


def test_bsram_block_count_is_not_zero_for_populated_memories(bsram_cfg):
    lift = GowinLift("GW1N-2")
    d = lift.recover_netlist(lift.parse_config(bsram_cfg))
    assert d.hardip_counts.get("BSRAM") == 1
    assert len(d.ebrs) == d.hardip_counts["BSRAM"]


# ============================================== ebr_buses classification =====

def test_gowin_bsram_bus_classification():
    from reach3 import _classify_ebr_port as cls
    assert cls("DIA0") == ("write_data", 0)
    assert cls("DIB0") == ("write_data", 64)
    assert cls("DI0") == ("write_data", 128)
    assert cls("DOA17") == ("read_data", 17)
    assert cls("ADB13") == ("addr", 64 + 13)
    assert cls("CLKA") == ("ctrl", 0)
    assert cls("RESETB") == ("ctrl", 64 + 4)
    assert cls("BLKSEL2") == ("ctrl", 128 + 8 + 2)


def test_gowin_bsram_bus_indices_never_collide():
    """UNIQUE(bitstream, block, bus_role, bit_index) — the A/B/unsuffixed views
    are three aliases of the same wires and must not overwrite one another."""
    from reach3 import _classify_ebr_port as cls
    ports = []
    for view in ("A", "B", ""):
        ports += [f"DI{view}{i}" for i in range(18)]
        ports += [f"DO{view}{i}" for i in range(18)]
        ports += [f"AD{view}{i}" for i in range(14)]
        ports += [f"BLKSEL{view}{i}" for i in range(3)]
        ports += [f"{s}{view}" for s in ("CLK", "CE", "OCE", "WRE", "RESET")]
    keys = [cls(p) for p in ports]
    assert None not in keys, "every BSRAM port must classify"
    assert len(set(keys)) == len(keys), "bit_index collision across port views"


def test_machxo2_ebr_classification_still_works():
    """The GOWIN branch must not shadow the MachXO2 JA/JC/JE naming."""
    from reach3 import _classify_ebr_port as cls
    assert cls("JA3") == ("write_data", 3)
    assert cls("JC0") == ("write_addr", 0)
    assert cls("JE1") == ("ctrl", 1)
    assert cls("NOT_A_PORT") is None
