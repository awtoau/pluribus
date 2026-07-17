"""Native (pure-Python) reimplementation of the pytrellis surface the pluribus
MachXO2 lifter and iomap depend on.

Goal: drop the pytrellis `.so` entirely.  The bitstream *decode* was already
ported (see scripts/native_bitstream.py); this package ports the remaining
piece -- the static routing graph (chip geometry + wire/bel connectivity +
`globalise_net` wire canonicalization) -- which is a pure function of the
device and therefore exhaustively parity-checkable against pytrellis.

Ported faithfully from the awtoau/prjtrellis fork:
  - geometry.py  <- Chip.cpp / Tile.cpp / Database.cpp
  - globalise.py <- RoutingGraph.cpp (globalise_net_machxo2 + globals)
  - rgraph.py    <- Chip.cpp get_routing_graph_machxo2 + tiletype DBs

The public facade mimics enough of pytrellis for a drop-in `import`.
"""
from .geometry import ChipGeometry, get_row_col, load_device_info

__all__ = ["ChipGeometry", "get_row_col", "load_device_info"]
