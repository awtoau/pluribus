"""Scope definitions -> object sets (docs/provenance-schema.md "Representation of bulk").

A scope row compresses a set of subjects. Bit-space scopes expand to flat indices
(frame * bits_per_frame + v) with numpy; key-space scopes to lists of subject keys.
Per-bit rows never exist; `n_objects` is always written from `count()`.

Geometry (`geom`) is the device's `devices.geometry` JSON: {"bits_per_frame", "frames",
"FX": {x: frame}, "vy0", "vpitch", "ymax", "col_kind": {x: kind}} for frame/v families.
"""
import json

import numpy as np

import db
from provenance import tiers


def canonical(space, kind, definition):
    """Stable scope_key: the unique string for (space, kind, definition)."""
    tiers.check(kind, tiers.SCOPE_KINDS, "scope kind")
    tiers.check(space, tiers.SPACES, "space")
    return f"{space}|{kind}|" + json.dumps(definition, sort_keys=True, separators=(",", ":"))


def _tiles_of_class(d, geom):
    """(x, y) pairs of a tile-class definition."""
    fx = {int(k): v for k, v in geom["FX"].items()}
    kinds = {int(k): v for k, v in geom.get("col_kind", {}).items()}
    xs = sorted(fx)
    if "col_kind" in d:
        xs = [x for x in xs if kinds.get(x) == d["col_kind"]]
    if "x_range" in d:
        lo, hi = d["x_range"]
        xs = [x for x in xs if lo <= x <= hi]
    if "x_in" in d:
        xs = [x for x in xs if x in set(d["x_in"])]
    if "x_not" in d:
        xs = [x for x in xs if x not in set(d["x_not"])]
    ylo, yhi = d.get("y_range", [1, geom["ymax"] - 1])
    ys = list(range(ylo, yhi + 1))
    if "y_in" in d:
        ys = [y for y in ys if y in set(d["y_in"])]
    xm, ym = d.get("x_mod"), d.get("y_mod")
    if xm:
        xs = [x for x in xs if x % xm in set(d.get("x_res", [x % xm]))]
    if ym:
        ys = [y for y in ys if y % ym in set(d.get("y_res", [y % ym]))]
    return [(x, y) for x in xs for y in ys]


def _tile_cells(x, y, offsets, geom):
    nv = geom["bits_per_frame"]
    fx = geom["FX"][str(x)] if str(x) in geom["FX"] else geom["FX"][x]
    vy = geom["vy0"] + geom["vpitch"] * y
    off = np.asarray(offsets, np.int64).reshape(-1, 2)
    return (fx + off[:, 0]) * nv + vy + off[:, 1]


def expand(kind, definition, geom=None):
    """-> np.ndarray of flat bit indices (bit spaces) or a list of subject keys (key spaces)."""
    d = definition
    if kind == "cells":
        nv = geom["bits_per_frame"] if geom else d.get("bits_per_frame")
        if "flat" in d:
            return np.unique(np.asarray(d["flat"], np.int64))
        c = np.asarray(d["cells"], np.int64).reshape(-1, 2)
        return np.unique(c[:, 0] * nv + c[:, 1])
    if kind == "range":
        nv = geom["bits_per_frame"]
        f0, f1 = d["frames"]
        v0, v1 = d.get("v", [0, nv - 1])
        fr = np.arange(f0, f1 + 1, dtype=np.int64)
        vv = np.arange(v0, v1 + 1, dtype=np.int64)
        return (fr[:, None] * nv + vv[None, :]).ravel()
    if kind == "tile":
        return np.unique(_tile_cells(d["x"], d["y"], d["offsets"], geom))
    if kind == "tile-class":
        tiles = _tiles_of_class(d, geom)
        if not tiles:
            return np.zeros(0, np.int64)
        off = np.asarray(d["offsets"], np.int64).reshape(-1, 2)
        nv = geom["bits_per_frame"]
        fx = np.array([geom["FX"][str(x)] for x, _ in tiles], np.int64)
        vy = geom["vy0"] + geom["vpitch"] * np.array([y for _, y in tiles], np.int64)
        return np.unique(((fx[:, None] + off[None, :, 0]) * nv + vy[:, None] + off[None, :, 1]).ravel())
    if kind == "keys":
        return list(d["keys"])
    if kind == "all":
        return np.arange(d["n"], dtype=np.int64) if "n" in d else []
    if kind == "formula":
        db.die(f"formula scopes are expanded by their matcher ({d.get('matcher')}), not here")
    db.die(f"unknown scope kind {kind!r}")


def count(kind, definition, geom=None):
    """n_objects for a scope row. formula scopes carry their own count."""
    if kind == "formula":
        return int(definition.get("n_objects", 0))
    if kind == "all":
        return int(definition.get("n", 0))
    if kind == "tile-class" and definition.get("count_only"):
        return len(_tiles_of_class(definition, geom)) * len(definition["offsets"])
    out = expand(kind, definition, geom)
    return int(len(out))


def intersects(a_kind, a_def, b_kind, b_def, geom=None):
    """Do two scopes share any object? (bit spaces via expansion; key spaces via set overlap)."""
    A, B = expand(a_kind, a_def, geom), expand(b_kind, b_def, geom)
    if isinstance(A, list) or isinstance(B, list):
        return bool(set(A) & set(B))
    return bool(np.intersect1d(A, B, assume_unique=True).size)


def specificity(kind):
    return tiers.SCOPE_SPECIFICITY[kind]
