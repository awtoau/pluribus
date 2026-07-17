"""Parse a MachXO2 tiletype connectivity DB (`tiledata/<type>/bits.db`).

We only need the routing records for the port:
  * `.mux <sink>` + following `<source> <bits...>` lines  (configurable arcs)
  * `.fixed_conn <sink> <source>`                          (fixed arcs)
The `.config` / `.config_enum` records (non-routing settings) are skipped.

Mirrors TileBitDatabase::operator>> (BitDatabase.cpp:450-472): records are
whitespace/'.'-token delimited; a `.mux` record ends at a blank line
(skip_check_eor).  Returns muxes {sink: [source, ...]} and a list of
(sink, source) fixed connections -- exactly what add_routing consumes.
"""
import os
from functools import lru_cache


def _parse(path):
    muxes = {}          # sink -> [source, ...]
    fixed = []          # [(sink, source), ...]
    mode = None         # None | "mux" | "skip"
    cur_sink = None
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                mode = None        # blank line terminates a .mux record
                continue
            toks = line.split()
            t0 = toks[0]
            if t0 == ".mux":
                cur_sink = toks[1]
                muxes.setdefault(cur_sink, [])
                mode = "mux"
            elif t0 == ".fixed_conn":
                fixed.append((toks[1], toks[2]))
                mode = None
            elif t0.startswith("."):
                mode = "skip"      # .config / .config_enum / anything else
            elif mode == "mux":
                muxes[cur_sink].append(t0)   # source is the first token
            # else: skip config bit lines
    return muxes, fixed


@lru_cache(maxsize=None)
def load_tiletype(db_root, family, tiletype):
    """(muxes, fixed_conns) for a tiletype -- cached (static per install)."""
    path = os.path.join(db_root, family, "tiledata", tiletype, "bits.db")
    return _parse(path)
