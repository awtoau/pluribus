#!/usr/bin/env python3.15t
"""Build the LI driver block → LI index positional map for EP4CGX150 (issue #139).

Algorithm: for each LOCAL_INTERCONNECT edge in the RCF, the learner identifies
(src_tile, li_index). Dec.active finds which asm block at that tile fires with a
non-default source AND whose icname [k] == li_index. That block's (tile_class, bkey)
is the silicon signature for "drives LI[li_index] at dy offset". Aggregate with voting
across even designs; verify on odd designs.

Output: lifters/data/cycloneiv_ep4cgx150_li_map.json
  {"class": {"x_mod":8,"y_mod":4},
   "lis": {"<class>|<key>": [dy, li_index], ...},
   "stats": {...}, "designs": [...]}

  python3.15t scripts/cycloneiv_li_map.py extract  [--designs 'gx150_*'] [--split even]
  python3.15t scripts/cycloneiv_li_map.py verify   [--designs 'gx150_*'] [--split odd]
Log: tmp/logs/cycloneiv_li_map.log.  Needs Dec prepared arrays + rl_gx_m8f.json.
"""
import argparse
import collections
import json
import logging
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "lifters"))

import cycloneiv_asm_decode as D          # noqa: E402
import cycloneiv_corpus as cc             # noqa: E402
import cycloneiv_geom as cg               # noqa: E402
import cycloneiv_phys_trace as pt         # noqa: E402
import cycloneiv_route_decode as rd       # noqa: E402
import cycloneiv_route_learn as rl        # noqa: E402

log = logging.getLogger("cycloneiv_li_map")
OUT = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_li_map.json")
TABLES = os.path.join(REPO, "tmp", "cycloneiv", "rl_gx_m8f.json")
XM, YM = 8, 4
MIN_RAM_GB = 20


def _check_ram():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    if kb < MIN_RAM_GB * 1024 * 1024:
                        log.error("only %d GB free, need %d", kb // 1024 // 1024, MIN_RAM_GB)
                        sys.exit(1)
                    return
    except OSError:
        pass


def _instances_li(name, d, geom):
    """LOCAL_INTERCONNECT instances: [(src_x, src_y, li_index)]."""
    out = []
    for key, dst_x, dst_y, src in rl.instances(name, d, geom):
        if src[0] == "LOCAL_INTERCONNECT":
            _t, _s, li_idx, dx, dy = src
            out.append((dst_x + dx, dst_y + dy, li_idx))
    return out


def extract(P, names, geom):
    """Vote (tile_class, bkey_id) -> (dy, li_index) across even designs.

    For each LOCAL_INTERCONNECT RCF edge in a design: the source tile (src_x, src_y)
    has li_index i. Among asm blocks fired at (src_x + 0, src_y - block_dy) for
    block_dy in {0, -1, 1}: the unique block with icname [k] == li_index AND
    src_code != -1 is the LI driver. Vote across designs; accept if a (dy, li_idx)
    candidate has at least twice the votes of the runner-up (or is the only candidate).
    """
    _check_ram()
    t0 = time.time()
    # vote[(tc, kid, block_dy, li_idx)] = count
    votes = collections.Counter()
    n_inst_total = 0
    n_matched_total = 0

    for di, name in enumerate(names):
        d = cc.load(name)
        plane = d["plane"]
        gids, recs, bids = P.dec.active(plane)

        # per-tile: list of (bid, src_code, k_icname)
        tile_blocks = collections.defaultdict(list)
        for bid, srec in zip(bids.tolist(), recs.tolist()):
            tx, ty = int(P.btx[bid]), int(P.bty[bid])
            sc = P.src_code(bid, srec)
            nm = P.dec.names.get(srec, "?")
            m = D.NAME.match(nm)
            k_val = int(m.group(9)) if m else -1
            tile_blocks[(tx, ty)].append((int(P.bkey[bid]), sc, k_val))

        li_insts = _instances_li(name, d, geom)
        n_inst_total += len(li_insts)

        for src_x, src_y, li_idx in li_insts:
            # try block_dy in {0, -1, 1}: block at (src_x, src_y - block_dy)
            for block_dy in (0, -1, 1):
                tile_x, tile_y = src_x, src_y - block_dy
                cands = [(kid, sc) for kid, sc, k in tile_blocks.get((tile_x, tile_y), [])
                         if k == li_idx and sc != -1]
                if len(cands) == 1:
                    kid, _sc = cands[0]
                    tc = pt.tile_class(tile_x, tile_y, XM, YM)
                    votes[(tc, kid, block_dy, li_idx)] += 1
                    n_matched_total += 1
                    break

        if di % 20 == 19:
            log.info("extract: %d / %d designs, %d li_insts, %d matched (%.0fs)",
                     di + 1, len(names), n_inst_total, n_matched_total, time.time() - t0)

    log.info("extract done: %d designs, %d li_insts, %d matched (%.0fs)",
             len(names), n_inst_total, n_matched_total, time.time() - t0)

    # resolve: for each (tc, kid) pick the (dy, li_idx) with clear majority
    per_key = collections.defaultdict(list)
    for (tc, kid, dy, li_idx), cnt in votes.items():
        per_key[(tc, kid)].append((cnt, dy, li_idx))

    lis_map = {}
    stats = collections.Counter()
    for (tc, kid), entries in per_key.items():
        entries.sort(reverse=True)
        best_cnt, best_dy, best_li = entries[0]
        if len(entries) == 1 or best_cnt > entries[1][0] * 2:
            lis_map[(tc, kid)] = (best_dy, best_li)
            stats["resolved"] += 1
        else:
            stats["ambiguous"] += 1

    # coverage: resolved per class
    by_class = collections.Counter(tc for tc, kid in lis_map)
    for cls in sorted(by_class):
        log.info("  class %2d: %d entries", cls, by_class[cls])

    log.info("resolved %d, ambiguous %d", stats["resolved"], stats["ambiguous"])

    # write output
    out = {
        "class": {"x_mod": XM, "y_mod": YM},
        "designs": names,
        "lis": {f"{tc}|{P.keys[kid]}": list(v) for (tc, kid), v in lis_map.items()},
        "stats": dict(stats),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=0)
    log.info("wrote %s (%d entries)", OUT, len(lis_map))
    return lis_map


def verify(P, names, geom, lis_map=None):
    """For each LOCAL_INTERCONNECT edge in odd designs: check that the resolved block
    fires (src_code != -1) for the predicted (dy, li_index). Report agreement rate."""
    if lis_map is None:
        raw = json.load(open(OUT))
        lis_map = {
            (int(k.split("|")[0]), P.key_id[k.split("|", 1)[1]]): tuple(v)
            for k, v in raw["lis"].items()
            if k.split("|", 1)[1] in P.key_id
        }
    # li_inv: (tc, li_idx) -> (kid, dy) — last writer wins on collision (same as PhysTracer)
    li_inv = {(tc, li): (kid, dy) for (tc, kid), (dy, li) in lis_map.items()}

    t0 = time.time()
    ok, miss = collections.Counter(), collections.Counter()
    for di, name in enumerate(names):
        d = cc.load(name)
        plane = d["plane"]
        gids, recs, bids = P.dec.active(plane)

        # per-tile: {(tx,ty): {bkey_id: max_src_code}} — non-default (-1) overwritten by actual code
        tile_fired = collections.defaultdict(dict)
        for bid, srec in zip(bids.tolist(), recs.tolist()):
            tx, ty = int(P.btx[bid]), int(P.bty[bid])
            sc = P.src_code(bid, srec)
            kid = int(P.bkey[bid])
            prev = tile_fired[(tx, ty)].get(kid, -1)
            if sc > prev:
                tile_fired[(tx, ty)][kid] = sc

        li_insts = _instances_li(name, d, geom)
        for src_x, src_y, li_idx in li_insts:
            tc = pt.tile_class(src_x, src_y, XM, YM)
            hit = li_inv.get((tc, li_idx))
            if hit is None:
                miss["not_in_map"] += 1
                continue
            kid, dy = hit
            tile_x, tile_y = src_x, src_y - dy
            best_sc = tile_fired.get((tile_x, tile_y), {}).get(kid, -1)
            if best_sc != -1:
                ok["li"] += 1
            else:
                miss["li_not_fired"] += 1
        if di % 20 == 19:
            log.info("verify: %d / %d designs (%.0fs)", di + 1, len(names), time.time() - t0)

    total = ok["li"] + miss["li_not_fired"] + miss["not_in_map"]
    log.info("verify %d designs: li matched %d / %d (%.1f%%)  not_in_map %d  not_fired %d",
             len(names), ok["li"], total, 100 * ok["li"] / max(1, total),
             miss["not_in_map"], miss["li_not_fired"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("extract", "verify"))
    ap.add_argument("--designs", default="gx150_*")
    ap.add_argument("--split", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tables", default=TABLES)
    a = ap.parse_args()

    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_li_map.log"), "w"),
        ],
    )

    split = a.split or ("even" if a.cmd == "extract" else "odd")
    names = [n for n in cc.designs(a.designs) if rl.split_of(n, split)]
    if a.limit:
        names = names[:a.limit]
    log.info("cmd=%s split=%s designs=%d", a.cmd, split, len(names))

    geom = cg.load("ep4cgx150")
    P = pt.Phys(need_map=False)

    if a.cmd == "extract":
        extract(P, names, geom)
    else:
        verify(P, names, geom)


if __name__ == "__main__":
    main()
