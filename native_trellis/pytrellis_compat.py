"""A pure-Python drop-in for the slice of the pytrellis API the pluribus
MachXO2 lifter and fpga_iomap use.  Import it in place of `pytrellis`:

    from native_trellis import pytrellis_compat as pytrellis

Backed by native_trellis.rgraph (no .so).  Wire/bel/pin "id"s are the wire
NAME strings (pytrellis interns names to ints and always resolves them via
to_str; using the string directly is equivalent and makes to_str the identity).

Surface provided (exactly what the two callers touch):
  load_database(path)
  Location(x, y)                       -> hashable (x, y)
  Chip(device):
      .get_max_row() / .get_max_col()
      .get_tiles_by_position(row, col) -> [obj with .info.name/.info.type]
      .get_routing_graph(a, b)         -> RoutingGraph
  RoutingGraph:
      .max_row / .max_col / .chip_family
      .tiles[Location(x, y)]           -> tile with .wires{name:Wire}/.bels{name:Bel}
      .to_str(id)                      -> id (identity)
      .globalise_net(row, col, name)   -> RoutingId(.loc.x/.loc.y/.id)
  Bel.pins[pin] = (RoutingId wire, direction)
"""
from collections import namedtuple

from .rgraph import NativeRoutingGraph

Location = namedtuple("Location", ["x", "y"])
RoutingId = namedtuple("RoutingId", ["loc", "id"])
_Wire = namedtuple("RoutingWire", ["id"])
_Bel = namedtuple("RoutingBel", ["name", "type", "z", "pins"])
_TileInfo = namedtuple("TileInfo", ["name", "type"])

PORT_IN, PORT_OUT = 0, 1
# invalid globalise result == RoutingId() default in C++ (loc (-1,-1), id -1)
_INVALID = RoutingId(Location(-1, -1), -1)

_state = {"dbroot": None}


def load_database(path):
    _state["dbroot"] = path


class _Tile:
    __slots__ = ("loc", "wires", "bels")

    def __init__(self, loc, wires, bels):
        self.loc = loc
        self.wires = wires   # {name: _Wire}
        self.bels = bels     # {belname: _Bel}


class _TileObj:
    """get_tiles_by_position element: exposes .info.name / .info.type."""
    __slots__ = ("info",)

    def __init__(self, name, type_):
        self.info = _TileInfo(name, type_)


class RoutingGraph:
    def __init__(self, native):
        self._n = native
        self.max_row = native.max_row
        self.max_col = native.max_col
        self.chip_family = native.family
        self.chip_name = native.device
        self.tiles = self._build_tiles(native)

    @staticmethod
    def _build_tiles(n):
        tiles = {}
        for x in range(n.max_col + 1):
            for y in range(n.max_row + 1):
                loc = Location(x, y)
                wires = {nm: _Wire(nm) for nm in n.wires.get((x, y), ())}
                bels = {}
                for bn, b in n.bels.get((x, y), {}).items():
                    pins = {}
                    for pin, rid in b.pins.items():
                        pins[pin] = (RoutingId(Location(rid.x, rid.y), rid.name),
                                     PORT_IN)  # direction unused by the lifter
                    bels[bn] = _Bel(b.name, b.type, b.z, pins)
                tiles[loc] = _Tile(loc, wires, bels)
        return tiles

    def to_str(self, ident):
        return ident  # ids ARE the name strings

    def globalise_net(self, row, col, name):
        r = self._n.globalise_net(row, col, name)
        if r is None:
            return _INVALID
        return RoutingId(Location(r.x, r.y), r.name)


class Chip:
    def __init__(self, device):
        db = _state["dbroot"]
        if db is None:
            raise RuntimeError("call load_database() before Chip()")
        self._native = NativeRoutingGraph(device, db)
        self._rg = None
        self.info = _TileInfo(device, self._native.family)

    def get_max_row(self):
        return self._native.max_row

    def get_max_col(self):
        return self._native.max_col

    def get_tiles_by_position(self, row, col):
        return [_TileObj(name, ttype) for (name, ttype)
                in self._native.geom.get_tiles_by_position(row, col)]

    def get_routing_graph(self, include_lutperm_pips=True, split_slice_mode=True):
        if self._rg is None:
            self._rg = RoutingGraph(self._native)
        return self._rg
