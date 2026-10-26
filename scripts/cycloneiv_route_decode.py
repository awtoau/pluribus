"""Cyclone IV routing decode from learnt mux tables (cycloneiv_route_learn.py output).

Decoder(paths).source(plane, geom, dst_key, x, y) -> (src_key_str | None, reason).
- Tables are tried in the order given (e.g. per-column first, then pooled by X mod 8); the first
  table whose pattern lookup is unique decides.  A pattern matching several sources in one table
  is 'ambiguous' and falls through to the next table.
- src_key_str = "TYPE|S|I|dx|dy" (wire) or "DRV|<cell kind>|N|dx|dy" relative to the dst tile.
"""
import collections
import json

import numpy as np
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
    if not mux:
        return ()
    fs = np.array([f0 + df + rl.WF[0] for df, _ in mux])
    vs = np.array([v0 + dv + rl.WV[0] for _, dv in mux])
    hit = plane.has(fs, vs)
    return tuple(m for m, h in zip(mux, hit) if h)


class AsmSource:
    """Exact tables from the Quartus asm.ddb (cycloneiv_asm_tables): per plane, the selected input of
    every mux the block map names.  Sources come back as learner-style keys; a wire has one key per RCF
    alias (the RCF names a wire by its driver point), so several candidates are normal."""

    def __init__(self, path=None):
        import cycloneiv_asm_decode as ad
        import cycloneiv_asm_tables as at
        self.t = at.Tables(ad.Dec(), path) if path else at.Tables(ad.Dec())
        self._cache = {}

    def decoded(self, plane):
        dec = self._cache.get(id(plane))
        if dec is None:
            self._cache.clear()               # one design at a time
            dec = self._cache[id(plane)] = self.t.decode_design(plane)
        return dec

    def sources(self, plane, key, x, y):
        rec = self.decoded(plane).get((x, y, tuple(key)))
        if rec is None:
            return None
        return self.t.rcf_names(rec, x, y)

    def extra_at(self, plane, x, y, used):
        """Muxes of tile (x, y) the asm tables decode to a source but the RCF does not use."""
        return sum(1 for (dx, dy, key) in self.decoded(plane) if dx == x and dy == y and (key, x, y) not in used)


class Decoder:
    def __init__(self, paths, asm=None):
        self.tables = [Table(p) for p in paths]
        self.asm = asm
        self._idx = {}

    def groups_in_class(self, t, cls):
        """[(key tuple, (mux, pats, anchor))] of one table for a tile class."""
        ix = self._idx.get(id(t))
        if ix is None:
            ix = self._idx[id(t)] = collections.defaultdict(list)
            for k, g in t.groups.items():
                p = k.split("|")
                ix[p[0]].append((tuple([p[1]] + [int(q) if q.lstrip("-").isdigit() else q for q in p[2:]]), g))
        return ix.get(cls, [])

    def extra_in_tile(self, plane, geom, x, y, used):
        """Count wire/mux groups at tile (x, y) NOT used by the design whose mux bits read as a
        known single source (an extra connection the RCF does not have)."""
        n = 0
        t = self.tables[0]
        asm_dec = self.asm.decoded(plane) if self.asm is not None else {}
        n += sum(1 for (dx, dy, key) in asm_dec if dx == x and dy == y and (key, x, y) not in used)
        for key, (mux, pats, (ax, ay)) in self.groups_in_class(t, rl.tile_class(geom, x, y, t.col_phase)):
            if (key, x, y) in used or not mux or (x, y, key) in asm_dec:
                continue
            bits = read_bits(plane, geom, x + ax, y + ay, mux)
            if bits:
                got = pats.get(bits)
                n += bool(got) and len(got) == 1
        return n

    def source(self, plane, geom, key, x, y):
        cands, reason = self.sources(plane, geom, key, x, y)
        if len(cands) == 1:
            return cands[0], "ok"
        return None, reason if not cands else "ambiguous pattern"

    def nonzero(self, plane, geom, key, x, y):
        """True when the first table's mux bits of this group read nonzero (the mux is driven)."""
        for t in self.tables:
            g = t.groups.get(f"{rl.tile_class(geom, x, y, t.col_phase, key[0])}|{'|'.join(map(str, key))}")
            if g is not None:
                mux, _pats, (ax, ay) = g
                return bool(read_bits(plane, geom, x + ax, y + ay, mux))
        return False

    def sources(self, plane, geom, key, x, y):
        """All candidate sources from the first table with a pattern hit (several = ambiguous;
        a unique hit in a later table wins over an ambiguous earlier one)."""
        reason, amb = "no table", None
        if key[0] == "FF" and key[2] in rl.FF_LAB_PORTS:
            key = rl.ff_lab_key(plane, geom, x, y, key[1], key[2])
        if x not in geom.kind or not 0 <= y <= geom.ymax:
            return [], "off die"
        if self.asm is not None:            # exact asm tables first; the learner only where they have no entry
            got = self.asm.sources(plane, key, x, y)
            if got:
                return (got, "ok") if len(got) == 1 else (got, "asm alias")   # one wire, several RCF names
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

    def __init__(self, dec, plane, geom, terminals=()):
        self.dec, self.plane, self.geom = dec, plane, geom
        self.terminals = set(terminals)    # wire types that end a trace (boundary nets)
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
            elif k2[0] == "CONST":
                found.add(("CONST", k2[1], 0, 0, 0))
            elif k2[0] == "CIN":
                found.add(("CIN", 0, 0, x, y))
            elif k2[0] == "LUTOUT":
                found.add(("LUTOUT", 0, 0, x, y))
            elif k2[0] in self.terminals:
                found.add(("WIRE", k2[0], k2[1], k2[2], x + dx, y + dy))
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
