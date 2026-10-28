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
import os
import threading
import weakref
from collections import namedtuple
from collections.abc import Mapping

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


class _WireMap(Mapping):
    """{name: _Wire} view over the native wire-name set; _Wire made on access, nothing stored."""
    __slots__ = ("_names",)

    def __init__(self, names):
        self._names = names

    def __getitem__(self, name):
        if name not in self._names:
            raise KeyError(name)
        return _Wire(name)

    def __contains__(self, name):
        return name in self._names

    def __iter__(self):
        return iter(self._names)

    def __len__(self):
        return len(self._names)


class _TileMap(Mapping):
    """{Location: _Tile} built on demand from the native graph.

    Stores nothing and mutates nothing after construction, so any number of threads
    can read it; each access returns a fresh _Tile (callers must not rely on identity).
    """

    def __init__(self, native):
        self._n = native

    def _in_grid(self, loc):
        try:
            x, y = loc
        except (TypeError, ValueError):
            return False
        return 0 <= x <= self._n.max_col and 0 <= y <= self._n.max_row

    def __getitem__(self, loc):
        if not self._in_grid(loc):
            raise KeyError(loc)
        x, y = loc
        n = self._n
        bels = {}
        for bn, b in n.bels.get((x, y), {}).items():
            pins = {pin: (RoutingId(Location(rid.x, rid.y), rid.name), PORT_IN)
                    for pin, rid in b.pins.items()}   # direction unused by the lifter
            bels[bn] = _Bel(b.name, b.type, b.z, pins)
        return _Tile(Location(x, y), _WireMap(n.wires.get((x, y), frozenset())), bels)

    def __contains__(self, loc):
        return self._in_grid(loc)

    def __iter__(self):
        n = self._n
        return (Location(x, y) for x in range(n.max_col + 1) for y in range(n.max_row + 1))

    def __len__(self):
        return (self._n.max_col + 1) * (self._n.max_row + 1)


class RoutingGraph:
    def __init__(self, native):
        self._n = native
        self.max_row = native.max_row
        self.max_col = native.max_col
        self.chip_family = native.family
        self.chip_name = native.device
        self.tiles = _TileMap(native)

    def has_wire(self, col, row, name):
        """True if tile (col, row) has wire `name` (no _Tile built)."""
        return name in self._n.wires.get((col, row), ())

    def to_str(self, ident):
        return ident  # ids ARE the name strings

    def globalise_net(self, row, col, name):
        r = self._n.globalise_net(row, col, name)
        if r is None:
            return _INVALID
        return RoutingId(Location(r.x, r.y), r.name)


class _Shared:
    """Read-only graph state shared by every Chip of one (device, db, family)."""

    def __init__(self, native):
        self.native = native
        self.rg = None
        self.lock = threading.Lock()


# Per-(device, db, family) read-only graph, built once per process.  PLURIBUS_RGRAPH_CACHE:
#   strong (default) - kept for the process lifetime (<= one entry per device, all idle between lifts)
#   weak             - freed when the last Chip using it goes (old behaviour: rebuilt per serial lift)
_SHARED = {}
_WEAK = weakref.WeakValueDictionary()
_SHARED_LOCK = threading.Lock()
_KEY_LOCKS = {}


def _shared_for(device, db, family):
    """One graph build per process per device, not one per lifter/worker."""
    key = (device, db, family)
    with _SHARED_LOCK:
        sh = _SHARED.get(key) or _WEAK.get(key)
        if sh is not None:
            return sh
        klock = _KEY_LOCKS.setdefault(key, threading.Lock())
    with klock:                              # other devices keep building meanwhile
        sh = _SHARED.get(key) or _WEAK.get(key)
        if sh is None:
            sh = _Shared(NativeRoutingGraph(device, db, family, keep_arcs=False))
            with _SHARED_LOCK:
                if os.environ.get("PLURIBUS_RGRAPH_CACHE", "strong") == "weak":
                    _WEAK[key] = sh
                else:
                    _SHARED[key] = sh
        return sh


def clear_shared():
    """Drop every cached graph (tests / memory reclaim)."""
    with _SHARED_LOCK:
        _SHARED.clear()


class Chip:
    def __init__(self, device, family=None):
        db = _state["dbroot"]
        if db is None:
            raise RuntimeError("call load_database() before Chip()")
        # family=None resolves from devices.json (MachXO2, ECP5, ...).
        self._shared = _shared_for(device, db, family)
        self._native = self._shared.native
        self.info = _TileInfo(device, self._native.family)

    def get_max_row(self):
        return self._native.max_row

    def get_max_col(self):
        return self._native.max_col

    def get_tiles_by_position(self, row, col):
        return [_TileObj(name, ttype) for (name, ttype)
                in self._native.geom.get_tiles_by_position(row, col)]

    def get_routing_graph(self, include_lutperm_pips=True, split_slice_mode=True):
        sh = self._shared
        with sh.lock:
            if sh.rg is None:
                sh.rg = RoutingGraph(sh.native)
        return sh.rg
