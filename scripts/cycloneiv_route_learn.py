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


# FF control pins pick one of two LAB lines with a per-LE select bit (LE-relative (frame, v),
# odd LEs mirrored); EP4CE6 held-out: CLK 1117/1117 LABs, CLRN 277/277 (cycloneiv_lab_controls.py).
# ENA shares the clock select.  SCLR / SLOAD are single LAB lines.
FF_SEL = {"CLK": (4, 2), "ENA": (4, 2), "CLRN": (3, 2)}
FF_LAB_PORTS = {"CLK", "ENA", "CLRN", "SCLR", "SLOAD"}


def le_bit(plane, geom, x, y, le, df, dv):
    f0, v0 = geom.anchor(x, y)
    s = -1 if le % 2 else 1
    return plane[f0 + df, v0 + geom.DN[le] + s * dv]


def ff_lab_key(plane, geom, x, y, n, port):
    """FF control pin -> the LAB line dst it reads: ("LAB<port>", 0, j)."""
    j = int(le_bit(plane, geom, x, y, n // 2, *FF_SEL[port])) if port in FF_SEL else 0
    return ("LAB" + port, 0, j)


def instances(name, d, geom=None):
    """[(group, x, y, src_key)] for every routed edge of a design.  With geom, FF control pins are
    re-expressed as LAB line dsts (ff_lab_key) so the line source is learnt like a mux."""
    vo, out = d["vo"], []
    for net, edges in d["rcf"].items():
        for src, dst in edges:
            a, b = node_at(vo, src), node_at(vo, dst)
            if a is None or b is None:
                continue
            bx, by, bkey = b
            ax, ay, akey = a
            if geom is not None and bkey[0] == "FF" and bkey[2] in FF_LAB_PORTS:
                bkey = ff_lab_key(d["plane"], geom, bx, by, bkey[1], bkey[2])
            out.append((bkey, bx, by, akey + (ax - bx, ay - by)))
    out += pseudo_instances(d, geom)
    return out


# Pins the RCF does not route are still muxes with a code: constants and the carry input.
LE_PORTS = ("dataa", "datab", "datac", "datad")
FF_PORTS = ("d", "asdata", "clrn", "sclr", "sload", "ena")


def pseudo_instances(d, geom=None):
    """(group, x, y, src) for pins the .vo ties to a constant (CONST 0 / 1) and for the DATAC pin
    of carry-mode LEs (CIN): the mux code that selects them, learnt like any other source."""
    vo, out = d["vo"], []
    for a in vo.atoms.values():
        loc = LOC.match(a.get("location") or "")
        if not loc or a["type"] not in ("cycloneive_lcell_comb", "dffeas"):
            continue
        kind, x, y, n = loc.group(1), int(loc.group(2)), int(loc.group(3)), int(loc.group(4))
        if kind == "LCCOMB":
            for p, _b, _d, net, _i, const in a["conns"]:
                if p in LE_PORTS and net is None and const in ("0", "1"):
                    out.append((("LCCOMB", n, p.upper()), x, y, ("CONST", int(const), 0, 0, 0)))
            if a["params"].get("sum_lutc_input") == "cin":
                out.append((("LCCOMB", n, "DATAC"), x, y, ("CIN", 0, 0, 0, 0)))
        elif kind == "FF":
            for p, _b, _d, net, _i, const in a["conns"]:
                if p in FF_PORTS and net is None and const in ("0", "1"):
                    key = ("FF", n, p.upper())
                    if geom is not None and key[2] in FF_LAB_PORTS:
                        key = ff_lab_key(d["plane"], geom, x, y, n, key[2])
                    out.append((key, x, y, ("CONST", int(const), 0, 0, 0)))
    return out


def window(plane, geom, x, y):
    f0, v0 = geom.anchor(x, y)
    return plane.rect(f0 + WF[0], f0 + WF[1], v0 + WV[0], v0 + WV[1])


ROW_PHASE = 4   # R4 / C4 indices rotate with Y mod 4 (an R4 index occurs at one row phase only)
# Row phase applies to every type: dropping it for LAB-local types (LE inputs, LE_BUFFER) lowered
# EP4CE6 held-out LE_BUFFER 99.4% -> 97.0% and LE inputs 74.7% -> 69.2%.
# Sink types: an unused LUT input may still be driven, so a sink mux bit may be set in up to
# SINK_UNUSED_MAX of the tiles where the RCF does not use that pin (wires: never).
SINKS = {"LCCOMB", "FF", "IOOBUF"}
SINK_UNUSED_MAX = 0.2


def tile_class(geom, x, y, col_phase=0, ktype=None):
    """Per column (LI/wire mux input order differs between LAB columns) and row phase."""
    col = f"{x}" if not col_phase else f"m{x % col_phase}"
    return f"{geom.col_kind(x)}{col}/{geom.row_kind(y)}/{y % ROW_PHASE}"


def one_geom(names):
    """The die geometry shared by every design (hard error on a mixed set)."""
    dies = {cg.die_of(cc.device_of(n)) for n in names}
    if len(dies) != 1:
        raise SystemExit(f"designs span dies {sorted(dies)}: pass a pattern for one die")
    return cg.load(dies.pop())


def split_of(name, split):
    if split == "all":
        return True
    h = zlib.crc32(name.encode()) & 1
    return h == (0 if split == "even" else 1)


# Where a wire's mux sits relative to the RCF coordinate (the driving end): candidate anchor
# offsets per dst type, chosen per group by the learner.  Others: the dst tile itself.
# C4 / C16 muxes can sit one column right of the RCF coordinate (EP4CGX150 C4 23: dx +1, dy +3/+4).
ANCHOR_CANDS = {"R4": [(dx, 0) for dx in range(-4, 5)],
                "C4": [(dx, dy) for dx in (0, 1) for dy in range(-4, 5)],
                "C16": [(dx, dy) for dx in (0, 1) for dy in range(-16, 17)],
                "R24": [(dx, 0) for dx in range(-24, 25)]}


SRCS = []   # source id -> source key tuple (filled in main, read by the workers)


def learn_group(cls, key, insts, planes, geom, used_tiles, tiles_of_class):
    """Try every anchor offset for the dst type; keep the one explaining the most sources."""
    best = None
    for off in ANCHOR_CANDS.get(key[0], [(0, 0)]):
        r = learn_group_at(off, key, insts, planes, geom, used_tiles, tiles_of_class)
        if r is None:
            continue
        sc = (sum(1 for p in r.get("pats", {}).values() if p), len(r["mux"]))
        if best is None or sc > best[0]:
            best = (sc, r)
    return best and best[1]


def learn_group_at(off, key, insts, planes, geom, used_tiles, tiles_of_class):
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
    mux = det & anyone & zero_unused
    pos = [tuple(int(t) for t in p) for p in np.argwhere(mux)]
    if not pos:
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
    ap.add_argument("--col-phase", type=int, default=0, help="pool LAB columns by X mod N (0 = per column)")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_route_learn.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = [n for n in cc.designs(a.train) if split_of(n, a.split)]
    geom = one_geom(names)
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
