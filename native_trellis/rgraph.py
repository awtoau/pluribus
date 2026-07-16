"""Build the native routing graph: per-tile wire sets + SLICE bels.

Ported from prjtrellis:
  - Chip.cpp get_routing_graph_machxo2   (tile loop; PLC SLICE bels)
  - BitDatabase.cpp add_routing          (muxes + fixed_conns -> wires/arcs)
  - Bels.cpp add_logic_comb/add_ff/add_ramw  (SLICE bel pin->wire maps)
  - RoutingGraph.cpp add_arc/add_wire/add_bel_input/output

Scope note: the pluribus lifter reads *arcs from the .config file*, not from
`rg.arcs`, and only ever looks up SLICE bels and per-tile wire NAMES (for the
`_SLICE` remap).  So we build the full wire set (for exact wire parity) and the
SLICE bels (add_logic_comb/add_ff/add_ramw, which is what split_slice_mode
uses), but skip the many non-SLICE bel builders (PLL/PIO/EFB/DCC/...) whose pin
wires the lifter never reads.  Arc/bel parity is checked exhaustively against
the pytrellis golden; the final gate is byte-identical netlist output.

Wire "id" == the wire NAME string (pytrellis interns names to ints and always
resolves them back via to_str; using the string directly is equivalent and
makes to_str the identity).
"""
from collections import namedtuple

from .geometry import ChipGeometry
from .globalise import Globaliser

RId = namedtuple("RId", ["x", "y", "name"])          # a wire reference
Arc = namedtuple("Arc", ["src", "sink", "configurable"])  # src/sink are RId
Bel = namedtuple("Bel", ["name", "type", "z", "pins"])    # pins: {pin: RId}


# --- SLICE bel builders (Bels.cpp:88-215). Each returns (bel_name, type, z,
#     pins{pin_name: local wire name}).  All wires are at the bel's own (x,y). --
_ABCD = "ABCD"


def _add_logic_comb(z):
    """add_logic_comb (Bels.cpp:88-152). `z` here is the 0..7 comb index."""
    l = _ABCD[z // 2]
    i = "01"[z % 2]
    pins = {}
    pins["A"] = f"A{z}_SLICE"
    pins["B"] = f"B{z}_SLICE"
    pins["C"] = f"C{z}_SLICE"
    pins["D"] = f"D{z}_SLICE"
    pins["M"] = f"M{z}_SLICE"
    if z < 4:
        pins["WAD0"] = f"WAD0{l}_SLICE"
        pins["WAD1"] = f"WAD1{l}_SLICE"
        pins["WAD2"] = f"WAD2{l}_SLICE"
        pins["WAD3"] = f"WAD3{l}_SLICE"
        pins["WD"] = f"WD{i}{l}_SLICE"
        pins["WRE"] = f"WRE{z // 2}_SLICE"
        pins["WCK"] = f"WCK{z // 2}_SLICE"
    if z == 0:
        pins["FCI"] = "FCI_SLICE"
    elif (z % 2) == 0:
        pins["FCI"] = f"FCI{l}_SLICE"
    else:
        pins["FCI"] = f"FCI{l}1_SLICE"
    pins["F"] = f"F{z}_SLICE"
    if (z % 2) == 0:
        pins["F1"] = f"F{z + 1}_SLICE"
        pins["OFX"] = f"F5{l}_SLICE"
    else:
        pins["FXA"] = f"FXA{l}_SLICE"
        pins["FXB"] = f"FXB{l}_SLICE"
        pins["OFX"] = f"FX{l}_SLICE"
    if z == 7:
        pins["FCO"] = "FCO_SLICE"
    elif (z % 2) == 1:
        pins["FCO"] = f"FCO{l}_SLICE"
    else:
        pins["FCO"] = f"FCI{l}1_SLICE"
    return f"SLICE{l}.K{i}", "TRELLIS_COMB", z * 4, pins


def _add_ff(z):
    """add_ff (Bels.cpp:154-178)."""
    l = _ABCD[z // 2]
    i = "01"[z % 2]
    pins = {
        "DI": f"DI{z}_SLICE",
        "M": f"M{z}_SLICE",
        "CLK": f"CLK{z // 2}_SLICE",
        "LSR": f"LSR{z // 2}_SLICE",
        "CE": f"CE{z // 2}_SLICE",
        "Q": f"Q{z}_SLICE",
    }
    return f"SLICE{l}.FF{i}", "TRELLIS_FF", z * 4 + 1, pins


def _add_ramw():
    """add_ramw (Bels.cpp:181-215)."""
    lc0, lc1 = 4, 5
    pins = {
        "A0": f"A{lc0}_SLICE", "B0": f"B{lc0}_SLICE",
        "C0": f"C{lc0}_SLICE", "D0": f"D{lc0}_SLICE",
        "A1": f"A{lc1}_SLICE", "B1": f"B{lc1}_SLICE",
        "C1": f"C{lc1}_SLICE", "D1": f"D{lc1}_SLICE",
        "WDO0": "WDO0C_SLICE", "WDO1": "WDO1C_SLICE",
        "WDO2": "WDO2C_SLICE", "WDO3": "WDO3C_SLICE",
        "WADO0": "WADO0C_SLICE", "WADO1": "WADO1C_SLICE",
        "WADO2": "WADO2C_SLICE", "WADO3": "WADO3C_SLICE",
    }
    return "SLICEC.RAMW", "TRELLIS_RAMW", 4 * 4 + 2, pins


class NativeRoutingGraph:
    """Pure-Python routing graph -- pytrellis-free."""

    def __init__(self, device, db_root, family="MachXO2", tiledb=None):
        self.device = device
        self.db_root = db_root
        self.geom = ChipGeometry(device, db_root, family)
        self.family = self.geom.family
        self.max_row = self.geom.max_row
        self.max_col = self.geom.max_col
        self.gl = Globaliser(device, self.max_row, self.max_col)

        # per-location structures
        self.wires = {}   # (x,y) -> set(name)
        self.arcs = {}    # (x,y) -> list[Arc]   (stored at the processing tile)
        self.bels = {}    # (x,y) -> {bel_name: Bel}

        if tiledb is None:
            from . import tiledb as _tiledb
            tiledb = _tiledb
        self._tiledb = tiledb
        self._build()

    def _wire(self, x, y, name):
        self.wires.setdefault((x, y), set()).add(name)

    def _build(self):
        gl = self.gl
        # Iterate every tilegrid tile (name -> type + row/col).
        for name, (row, col) in self.geom.tile_rc.items():
            ttype = self.geom.tile_type[name]
            muxes, fixed = self._tiledb.load_tiletype(
                self.db_root, self.family, ttype)
            ploc = (col, row)
            arclist = self.arcs.setdefault(ploc, [])

            # add_routing: configurable mux arcs
            for sink, sources in muxes.items():
                gsink = gl.globalise_net(row, col, sink)
                if gsink is None:
                    continue
                for src in sources:
                    gsrc = gl.globalise_net(row, col, src)
                    if gsrc is None:
                        continue
                    self._wire(*gsrc)
                    self._wire(*gsink)
                    arclist.append(Arc(gsrc, gsink, True))

            # add_routing: fixed connections
            for sink, src in fixed:
                gsink = gl.globalise_net(row, col, sink)
                if gsink is None:
                    continue
                gsrc = gl.globalise_net(row, col, src)
                if gsrc is None:
                    continue
                self._wire(*gsrc)
                self._wire(*gsink)
                arclist.append(Arc(gsrc, gsink, False))

            # SLICE bels for PLC tiles (split_slice_mode path).
            if ttype == "PLC":
                belmap = self.bels.setdefault((col, row), {})
                for z in range(8):
                    for bname, btype, bz, pins in (
                            _add_logic_comb(z), _add_ff(z)):
                        rpins = {}
                        for pin, wname in pins.items():
                            self._wire(col, row, wname)
                            rpins[pin] = RId(col, row, wname)
                        belmap[bname] = Bel(bname, btype, bz, rpins)
                bname, btype, bz, pins = _add_ramw()
                rpins = {}
                for pin, wname in pins.items():
                    self._wire(col, row, wname)
                    rpins[pin] = RId(col, row, wname)
                belmap[bname] = Bel(bname, btype, bz, rpins)

    # --- pytrellis-compatible-ish accessors (Stage E wraps these) -----------
    def get_max_row(self):
        return self.max_row

    def get_max_col(self):
        return self.max_col

    def globalise_net(self, row, col, name):
        return self.gl.globalise_net(row, col, name)

    def tile_wires(self, x, y):
        return self.wires.get((x, y), set())

    def tile_bels(self, x, y):
        return self.bels.get((x, y), {})
