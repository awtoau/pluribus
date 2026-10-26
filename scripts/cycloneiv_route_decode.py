"""Cyclone IV routing decode from learnt mux tables (cycloneiv_route_learn.py output).

Decoder(paths).source(plane, geom, dst_key, x, y) -> (src_key_str | None, reason).
- Tables are tried in the order given (e.g. per-column first, then pooled by X mod 8); the first
  table whose pattern lookup is unique decides.  A pattern matching several sources in one table
  is 'ambiguous' and falls through to the next table.
- src_key_str = "TYPE|S|I|dx|dy" (wire) or "DRV|<cell kind>|N|dx|dy" relative to the dst tile.
"""
import json
from pathlib import Path

import cycloneiv_route_learn as rl


class Table:
    def __init__(self, path):
        raw = json.loads(Path(path).read_text())
        meta = raw.pop("_meta", {})
        self.col_phase = meta.get("col_phase", 0)
        self.groups = {}
        for k, v in raw.items():
            pats = {}
            for s, p in v.get("pats", {}).items():
                pats.setdefault(tuple(tuple(q) for q in p), []).append(s)
            self.groups[k] = ([tuple(p) for p in v["mux"]], pats, tuple(v.get("anchor", (0, 0))))


def read_bits(plane, geom, x, y, mux):
    if x not in geom.FX:
        return None
    f0, v0 = geom.anchor(x, y)
    nf, nv = plane.shape
    on = []
    for df, dv in mux:
        f, v = f0 + df + rl.WF[0], v0 + dv + rl.WV[0]
        if 0 <= f < nf and 0 <= v < nv and plane[f, v]:
            on.append((df, dv))
    return tuple(on)


class Decoder:
    def __init__(self, paths):
        self.tables = [Table(p) for p in paths]

    def source(self, plane, geom, key, x, y):
        reason = "no table"
        for t in self.tables:
            g = t.groups.get(f"{rl.tile_class(geom, x, y, t.col_phase)}|{'|'.join(map(str, key))}")
            if g is None:
                continue
            mux, pats, (ax, ay) = g
            got = pats.get(read_bits(plane, geom, x + ax, y + ay, mux))
            if got is None:
                reason = "unknown pattern" if reason == "no table" else reason
                continue
            if len(got) > 1:
                reason = "ambiguous pattern"
                continue
            return got[0], "ok"
        return None, reason
