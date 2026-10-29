#!/usr/bin/env python3.15t
"""BANNED learner; retire with step 5.

Learn Cyclone IV routing-mux bit tables from the corpus (RCF = oracle), tile-relative.

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
# helpers moved to cycloneiv_common; re-exported so the learner and its remaining importers keep working
from cycloneiv_common import (  # noqa: E402,F401
    FF_LAB_PORTS, FF_PORTS, FF_SEL, LE_PORTS, LOC, ROW_PHASE, WF, WV,
    atom_xyn, ff_lab_key, instances, le_bit, node_at, one_geom, pseudo_instances, split_of, tile_class, window,
)

log = logging.getLogger("cycloneiv_route_learn")
MIN_SRC = 2


# Row phase applies to every type: dropping it for LAB-local types (LE inputs, LE_BUFFER) lowered
# EP4CE6 held-out LE_BUFFER 99.4% -> 97.0% and LE inputs 74.7% -> 69.2%.
# Sink types: an unused LUT input may still be driven, so a sink mux bit may be set in up to
# SINK_UNUSED_MAX of the tiles where the RCF does not use that pin (wires: never).
SINKS = {"LCCOMB", "FF", "IOOBUF"}
SINK_UNUSED_MAX = 0.2


# Where a wire's mux sits relative to the RCF coordinate (the driving end): candidate anchor
# offsets per dst type, chosen per group by the learner.  Others: the dst tile itself.
# C4 / C16 muxes can sit one column right of the RCF coordinate (EP4CGX150 C4 23: dx +1, dy +3/+4).
ANCHOR_CANDS = {"R4": [(dx, 0) for dx in range(-4, 5)],
                "C4": [(dx, dy) for dx in (0, 1) for dy in range(-4, 5)],
                "C16": [(dx, dy) for dx in (0, 1) for dy in range(-16, 17)],
                "R24": [(dx, 0) for dx in range(-24, 25)]}


TEMPLATE = {}   # (class without row phase, key str) -> mux bit positions seen at other row phases (--template)


def template_mask(cls, key, shape):
    pos = cls.endswith("/0") and TEMPLATE.get((cls.rsplit("/", 1)[0], "|".join(map(str, key))))
    m = np.zeros(shape, dtype=bool)
    for f, v in pos or ():
        m[f, v] = True
    return m


SRCS = []   # source id -> source key tuple (filled in main, read by the workers)


def learn_group(cls, key, insts, planes, geom, used_tiles, tiles_of_class):
    """Try every anchor offset for the dst type; keep the one explaining the most sources."""
    best = None
    for off in ANCHOR_CANDS.get(key[0], [(0, 0)]):
        r = learn_group_at(off, key, insts, planes, geom, used_tiles, tiles_of_class, cls)
        if r is None:
            continue
        sc = (sum(1 for p in r.get("pats", {}).values() if p), len(r["mux"]))
        if best is None or sc > best[0]:
            best = (sc, r)
    return best and best[1]


def learn_group_at(off, key, insts, planes, geom, used_tiles, tiles_of_class, cls=""):
    """insts: [(design, x, y, src)].  -> dict with mux bits and per-source patterns, or None.
    Streaming: per source only the AND / OR of its windows is kept (a stack of every window was
    1.5 GB for the large LE-input groups)."""
    ax, ay = off
    ok = lambda x, y: 0 <= x + ax <= geom.xmax and 0 <= y + ay <= geom.ymax  # noqa: E731
    by_src = collections.defaultdict(list)
    for p in insts:
        sidx = p & 0x3FFFFF
        y = (p >> 22) & 127
        x = (p >> 29) & 127
        di = p >> 36
        if ok(x, y):
            by_src[SRCS[sidx]].append((di, x, y))
    if not by_src:
        return None
    shape = (WF[1] - WF[0], WV[1] - WV[0])
    det = np.ones(shape, dtype=bool)        # constant within every well-sampled source
    anyone = np.zeros(shape, dtype=bool)
    every = np.ones(shape, dtype=bool)      # set in all instances of every well-sampled source
    for s, v in by_src.items():
        if len(v) < MIN_SRC:
            continue
        w_and = np.ones(shape, dtype=bool)
        w_or = np.zeros(shape, dtype=bool)
        for di, x, y in v:
            w = window(planes[di], geom, x + ax, y + ay)
            w_and &= w
            w_or |= w
        det &= w_and | ~w_or
        anyone |= w_and
        every &= w_and
    if not anyone.any() and not any(len(v) >= MIN_SRC for v in by_src.values()):
        return None
    # unused tiles: same class, dst not used in that design
    unused = [(di, x, y) for di in range(len(planes)) for (x, y) in tiles_of_class
              if ((di << 7 | x) << 7 | y) not in used_tiles and ok(x, y)]
    rng = np.random.default_rng(0)
    if len(unused) > 400:
        unused = [unused[i] for i in rng.choice(len(unused), 400, replace=False)]
    if unused:
        tot = np.zeros(shape, dtype=np.int32)
        for di, x, y in unused:
            tot += window(planes[di], geom, x + ax, y + ay)
        zero_unused = (tot == 0) if key[0] not in SINKS else (tot / len(unused) <= SINK_UNUSED_MAX)
    else:
        zero_unused = np.ones(shape, dtype=bool)
    if key[0].startswith("LAB") or key[0] == "FF":
        # FF control lines: the "off" choice can be a SET bit (SCLR const 0 = bit set), so the unused
        # tile rule would drop the select bits; keep bits that tell sources apart
        mux = det & anyone & ~every
    else:
        mux = det & anyone & (zero_unused | template_mask(cls, key, shape)) if TEMPLATE else det & anyone & zero_unused
    pos = [tuple(int(t) for t in p) for p in np.argwhere(mux)]
    if not pos:
        # one source and no select bit: the mux has a single legal input (BLK_CLK_BUF <- LAB_CLK)
        if len(by_src) == 1:
            src = next(iter(by_src))
            return {"mux": [], "n": len(insts), "srcs": 1, "pats": {src: ()}, "conflict_srcs": 0, "anchor": off}
        return {"mux": [], "n": len(insts), "srcs": len(by_src), "anchor": off}
    pats, conflict = {}, 0
    pf = np.array([p[0] + WF[0] for p in pos])
    pv = np.array([p[1] + WV[0] for p in pos])
    for s, v in by_src.items():
        sub = set()
        for di, x, y in v:
            f0, v0 = geom.anchor(x + ax, y + ay)
            hit = planes[di].has(f0 + pf, v0 + pv)
            sub.add(tuple(sorted(p for p, h in zip(pos, hit) if h)))
            if len(sub) > 1:
                break
        if len(sub) != 1:
            conflict += 1
            continue
        pats[s] = next(iter(sub))
    return {"mux": pos, "n": len(insts), "srcs": len(by_src), "pats": pats, "conflict_srcs": conflict,
            "anchor": off}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", default="rnd_*")
    ap.add_argument("--split", default="all", choices=["all", "even", "odd"])
    ap.add_argument("--types", default="", help="comma list of dst types to learn (default all)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--template", default=None, help="earlier table: its mux bits at other row phases are allowed "
                    "even where the unused-tile rule drops them (row phase 0 loses the second bit row)")
    ap.add_argument("--col-phase", type=int, default=0, help="pool LAB columns by X mod N (0 = per column)")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_route_learn.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = [n for n in cc.designs(a.train) if split_of(n, a.split)]
    geom = one_geom(names)
    if a.template:
        for k, v in json.loads(Path(a.template).read_text()).items():
            if k != "_meta" and v.get("mux"):
                c, rest = k.split("|", 1)
                if int(c.rsplit("/", 1)[1]) != 0:
                    TEMPLATE.setdefault((c.rsplit("/", 1)[0], rest), set()).update(map(tuple, v["mux"]))
    planes = []
    groups = collections.defaultdict(list)
    used = collections.defaultdict(set)
    sid = {}
    # instances are packed ints (design, x, y, source id): 15M tuples were > 3 GB
    for di, nm in enumerate(names):
        d = cc.load(nm)
        planes.append(d["plane"])
        for key, x, y, src in instances(nm, d, geom):
            cls = tile_class(geom, x, y, a.col_phase, key[0])
            i = sid.setdefault(src, len(sid))
            groups[(cls, key)].append((((di << 7 | x) << 7 | y) << 22) | i)
            used[(cls, key)].add(((di << 7 | x) << 7) | y)
        del d
    SRCS.extend(sorted(sid, key=sid.get))
    log.info("%d designs (%s, split %s), %d distinct sources", len(planes), a.train, a.split, len(sid))
    types = set(a.types.split(",")) if a.types else None
    tiles = collections.defaultdict(list)
    for x in range(geom.xmax + 1):
        for y in range(geom.ymax + 1):
            tiles[tile_class(geom, x, y, a.col_phase)].append((x, y))
            tiles[tile_class(geom, x, y, a.col_phase, "LCCOMB")].append((x, y))
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
    tab = {k: {**v, "pats": {"|".join(map(str, s)): p for s, p in v.get("pats", {}).items()}} for k, v in out.items()}
    tab["_meta"] = {"col_phase": a.col_phase, "die": geom.die, "train": a.train, "split": a.split,
                    "designs": len(planes)}
    path.write_text(json.dumps(tab, indent=0, default=list))
    log.info("wrote %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
