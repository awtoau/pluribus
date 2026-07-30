"""Native (pure-Python) reimplementation of the pytrellis surface pluribus needs.

Covers **MachXO2 and ECP5**, not MachXO2 alone -- `globalise.py` carries both
`globalise_net_machxo2` and `globalise_net_ecp5` behind a `make_globaliser(family,
...)` dispatcher.  This docstring claimed MachXO2-only for some time, which
understated the port and helped hide that nothing was parity-checking the ECP5
path (scripts/native_rgraph_parity.py instantiated the MachXO2 globaliser
directly and could not even construct one for an ECP5 device).

Goal: drop the pytrellis `.so` from the pipeline.  The bitstream *decode* and
*re-encode* are ported (scripts/native_bitstream.py); this package ports the
remaining piece -- the static routing graph (chip geometry + wire/bel
connectivity + `globalise_net` wire canonicalization) -- which is a pure function
of the device and therefore exhaustively parity-checkable against pytrellis.

Status: parity verified on every device in the database, all 16, both families --
85,921 tile positions, 30,727,715 `globalise_net` results and 1,052,606 SLICE bels
matching the `.so` exactly (scripts/rgraph_parity_sweep.py).  The lifters default
to this package; `PLURIBUS_TRELLIS_BACKEND=so` selects the `.so` for A/B work.

Ported faithfully from the awtoau/prjtrellis fork:
  - geometry.py  <- Chip.cpp / Tile.cpp / Database.cpp
  - globalise.py <- RoutingGraph.cpp (globalise_net_machxo2, globalise_net_ecp5)
  - rgraph.py    <- Chip.cpp get_routing_graph_* + tiletype DBs

The public facade mimics enough of pytrellis for a drop-in `import`.
"""
from .geometry import ChipGeometry, get_row_col, load_device_info

__all__ = ["ChipGeometry", "get_row_col", "load_device_info"]
