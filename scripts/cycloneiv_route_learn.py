#!/usr/bin/env python3.15t
"""Learn Cyclone IV routing-mux bit tables from the corpus (RCF = oracle), tile-relative.

Model:
- A routing element instance (dst) at tile (X, Y) selects one source.  Its mux bits sit at fixed
  offsets from anchor(X, Y) (cycloneiv_geom) for every tile of the same class.
- Group = (tile class, dst key).  dst key = (TYPE, S, I) for a wire; (cell kind, N, port) for a sink.
- Source key = (TYPE, S, I, dx, dy) for a wire, ("DRV", cell kind, N, dx, dy) for a cell output.
- Mux bits of a group: window bits that are a deterministic function of the source over every
  instance whose source is seen >= MIN_SRC times, and 0 in every tile of the class where the dst
  is unused.  Per-source pattern = the instance's bits on the mux set.

  python3.15t scripts/cycloneiv_route_learn.py [--train 'rnd_*'] [--split even|odd|all]
Output lifters/data/cycloneiv_<die>_routing.json; log tmp/logs/cycloneiv_route_learn.log
"""
import argparse
import collections
import json
import logging
import re
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402

log = logging.getLogger("cycloneiv_route_learn")
LOC = re.compile(r"^([A-Z0-9]+)_X(\d+)_Y(\d+)_N(\d+)$")
# Window around the anchor, (frame, v) relative.  Wide on purpose: wire muxes may sit a tile away.
WF = (-40, 41)
WV = (-110, 41)
MIN_SRC = 2


def atom_xyn(vo, name):
    a = vo.atoms.get(name)
    if a is None or not a.get("location"):
        return None
    m = LOC.match(a["location"])
    if not m:
        return None
    k, x, y, n = m.groups()
    return k, int(x), int(y), int(n)


def node_at(vo, node):
    """-> (x, y, key) for a dst/src node, or None when it has no fabric location."""
    if node[0] == "W":
        _, t, x, y, s, i = node
        return x, y, (t, s, i)
    if node[0] == "WB":
        _, t, x, y, s, path = node
        return x, y, (t, s, path)
    if node[0] == "SINK":
        loc = atom_xyn(vo, node[1])
        if loc is None:
            return None
        k, x, y, n = loc
        return x, y, (k, n, node[2])
    if node[0] == "DRV":
        loc = atom_xyn(vo, node[1])
        if loc is None:
            return None
        k, x, y, n = loc
        return x, y, ("DRV", k, n)
    raise ValueError(node)


def instances(name, d):
    """[(group, x, y, src_key)] for every routed edge of a design."""
    vo, out = d["vo"], []
    for net, edges in d["rcf"].items():
        for src, dst in edges:
            a, b = node_at(vo, src), node_at(vo, dst)
            if a is None or b is None:
                continue
            bx, by, bkey = b
            ax, ay, akey = a
            out.append((bkey, bx, by, akey + (ax - bx, ay - by)))
    return out


def window(plane, geom, x, y):
    f0, v0 = geom.anchor(x, y)
    nf, nv = plane.shape
    w = np.zeros((WF[1] - WF[0], WV[1] - WV[0]), dtype=bool)
    fa, fb = max(0, f0 + WF[0]), min(nf, f0 + WF[1])
    va, vb = max(0, v0 + WV[0]), min(nv, v0 + WV[1])
    if fa < fb and va < vb:
        w[fa - f0 - WF[0]:fb - f0 - WF[0], va - v0 - WV[0]:vb - v0 - WV[0]] = plane[fa:fb, va:vb]
    return w


def tile_class(geom, x, y):
    """Per column: LI/wire mux input order differs between LAB columns (measured; not a parity)."""
    return f"{geom.col_kind(x)}{x}/{geom.row_kind(y)}"


def split_of(name, split):
    if split == "all":
        return True
    h = zlib.crc32(name.encode()) & 1
    return h == (0 if split == "even" else 1)


def learn_group(cls, key, insts, planes, geom, used_tiles, tiles_of_class):
    """insts: [(design, x, y, src)].  -> dict with mux bits and per-source patterns, or None."""
    by_src = collections.defaultdict(list)
    for di, x, y, src in insts:
        by_src[src].append((di, x, y))
    wins = {s: np.stack([window(planes[di], geom, x, y) for di, x, y in v]) for s, v in by_src.items()}
    good = [s for s, v in by_src.items() if len(v) >= MIN_SRC]
    if not good:
        return None
    shape = next(iter(wins.values())).shape[1:]
    det = np.ones(shape, dtype=bool)        # constant within every well-sampled source
    anyone = np.zeros(shape, dtype=bool)
    for s in good:
        w = wins[s]
        det &= w.all(0) | (~w).all(0)
        anyone |= w.all(0)
    # unused tiles: same class, dst not used in that design
    unused = []
    for di in range(len(planes)):
        for (x, y) in tiles_of_class:
            if (di, x, y) not in used_tiles:
                unused.append((di, x, y))
    rng = np.random.default_rng(0)
    if len(unused) > 400:
        unused = [unused[i] for i in rng.choice(len(unused), 400, replace=False)]
    if unused:
        uw = np.stack([window(planes[di], geom, x, y) for di, x, y in unused])
        zero_unused = ~uw.any(0)
    else:
        zero_unused = np.ones(shape, dtype=bool)
    mux = det & anyone & zero_unused
    pos = [tuple(int(t) for t in p) for p in np.argwhere(mux)]
    if not pos:
        return {"mux": [], "n": len(insts), "srcs": len(by_src)}
    pats, conflict = {}, 0
    for s, v in by_src.items():
        w = wins[s]
        sub = [tuple(sorted(p for p in pos if w[i][p])) for i in range(len(v))]
        if len(set(sub)) != 1:
            conflict += 1
            continue
        pats[s] = sub[0]
    return {"mux": pos, "n": len(insts), "srcs": len(by_src), "pats": pats, "conflict_srcs": conflict}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", default="rnd_*")
    ap.add_argument("--split", default="all", choices=["all", "even", "odd"])
    ap.add_argument("--types", default="", help="comma list of dst types to learn (default all)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_route_learn.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    geom = cg.load("ep4ce6")
    names = [n for n in cc.designs(a.train) if split_of(n, a.split)]
    with ThreadPoolExecutor(a.workers) as ex:
        ds = list(ex.map(cc.load, names))
    planes = [d["plane"] for d in ds]
    log.info("%d designs (%s, split %s)", len(ds), a.train, a.split)
    groups = collections.defaultdict(list)
    used = collections.defaultdict(set)
    for di, d in enumerate(ds):
        for key, x, y, src in instances(d["name"], d):
            cls = tile_class(geom, x, y)
            groups[(cls, key)].append((di, x, y, src))
            used[(cls, key)].add((di, x, y))
    types = set(a.types.split(",")) if a.types else None
    tiles = collections.defaultdict(list)
    for x in range(geom.xmax + 1):
        for y in range(geom.ymax + 1):
            tiles[tile_class(geom, x, y)].append((x, y))
    out, stats = {}, collections.Counter()
    todo = [(g, v) for g, v in groups.items() if types is None or g[1][0] in types]
    log.info("%d groups", len(todo))

    def work(item):
        (cls, key), insts = item
        return (cls, key), learn_group(cls, key, insts, planes, geom, used[(cls, key)], tiles[cls])
    with ThreadPoolExecutor(a.workers) as ex:
        for (cls, key), r in ex.map(work, todo):
            if r is None:
                stats["undersampled"] += 1
                continue
            stats["with_mux" if r["mux"] else "no_mux_bits"] += 1
            out[f"{cls}|{'|'.join(map(str, key))}"] = r
    log.info("groups: %s", dict(stats))
    path = Path(a.out) if a.out else REPO / "tmp" / "cycloneiv" / f"route_learn_{a.split}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: {**v, "pats": {"|".join(map(str, s)): p for s, p in v.get("pats", {}).items()}}
                                for k, v in out.items()}, indent=0, default=list))
    log.info("wrote %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
