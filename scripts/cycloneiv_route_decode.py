"""Cyclone IV routing decode from learnt mux tables (cycloneiv_route_learn.py output).

Decoder(paths).source(plane, geom, dst_key, x, y) -> (src_key_str | None, reason).
- Tables are tried in the order given (e.g. per-column first, then pooled by X mod 8); the first
  table whose pattern lookup is unique decides.  A pattern matching several sources in one table
  is 'ambiguous' and falls through to the next table.
- src_key_str = "TYPE|S|I|dx|dy" (wire) or "DRV|<cell kind>|N|dx|dy" relative to the dst tile.
"""
import collections
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
        cands, reason = self.sources(plane, geom, key, x, y)
        if len(cands) == 1:
            return cands[0], "ok"
        return None, reason if not cands else "ambiguous pattern"

    def sources(self, plane, geom, key, x, y):
        """All candidate sources from the first table with a pattern hit (several = ambiguous;
        a unique hit in a later table wins over an ambiguous earlier one)."""
        reason, amb = "no table", None
        if x not in geom.kind or not 0 <= y <= geom.ymax:
            return [], "off die"
        for t in self.tables:
            g = t.groups.get(f"{rl.tile_class(geom, x, y, t.col_phase, key[0])}|{'|'.join(map(str, key))}")
            if g is None:
                continue
            mux, pats, (ax, ay) = g
            bits = read_bits(plane, geom, x + ax, y + ay, mux)
            # an all-zero mux can be a real code (default input: LE_BUFFER comb/FF, LE inputs);
            # unused muxes are zero too, so this is only sound when tracing from a used sink
            got = pats.get(bits)
            if got is None:
                if reason == "no table":
                    reason = "zero pattern" if bits == () else "unknown pattern"
                continue
            if len(got) == 1:
                return list(got), "ok"
            amb = amb or list(got)
        return (amb, "ambiguous pattern") if amb else ([], reason)


def parse_src(s):
    """'TYPE|S|I|dx|dy' or 'DRV|KIND|N|dx|dy' -> (kind tuple, dx, dy)."""
    p = s.split("|")
    if p[0] == "DRV":
        return ("DRV", p[1], int(p[2])), int(p[3]), int(p[4])
    return (p[0], int(p[1]), int(p[2])), int(p[3]), int(p[4])


MAX_HOPS = 40   # longest RCF branch seen on EP4CE6 is < 15 elements; deeper = a loop


class Tracer:
    """Follow decoded muxes from a sink back to a driving cell, memoised per design.
    trace() -> (("DRV", kind, n, x, y) | None, reason).  Ambiguous hops are resolved by keeping the
    candidates that reach a driver; more than one distinct driver = ambiguous."""

    def __init__(self, dec, plane, geom):
        self.dec, self.plane, self.geom = dec, plane, geom
        self.memo = {}          # (key, x, y) -> (frozenset(drivers), reason)

    def walk(self, key, x, y, depth, stack):
        if key[0] == "FF" and key[2] in rl.FF_LAB_PORTS:
            key = rl.ff_lab_key(self.plane, self.geom, x, y, key[1], key[2])
        node = (key, x, y)
        if node in self.memo:
            return self.memo[node]
        if depth > MAX_HOPS or node in stack:
            return frozenset(), "loop"
        cands, reason = self.dec.sources(self.plane, self.geom, key, x, y)
        if not cands:
            r = (frozenset(), f"{reason}:{key[0]}")
            self.memo[node] = r
            return r
        found, why = set(), None
        stack.add(node)
        for c in cands:
            k2, dx, dy = parse_src(c)
            if k2[0] == "DRV":
                found.add(("DRV", k2[1], k2[2], x + dx, y + dy))
            else:
                f, w = self.walk(k2, x + dx, y + dy, depth + 1, stack)
                found |= f
                why = why or w
        stack.discard(node)
        r = (frozenset(found), why or "dead end")
        self.memo[node] = r
        return r

    def trace(self, key, x, y):
        found, why = self.walk(tuple(key), x, y, 0, set())
        if len(found) == 1:
            return next(iter(found)), "ok"
        if found:
            return None, "ambiguous driver"
        return None, why


def trace(dec, plane, geom, key, x, y):
    return Tracer(dec, plane, geom).trace(key, x, y)
