#!/usr/bin/env python3.15t
"""TEST 2 of the blkrba hypothesis (#165): do the non-LUT named bits (REG/OUT/IN/RSCNT/RSMUX/ROWCLK) sit at
measured control cells?  Position law (TEST 1, cycloneiv_blkrba_lab.py): frame = FX[X] + dy - 15,
v = vy0 + 70*Y + 2 - dx.  Names come from the local csv (vendor-analysis, gitignored; never committed).

PREDICTION (written before the run, from the cells listed in docs/altera/cycloneIV/cycloneiv-bit-hunter.md)
- P1: LE-used cell (df -8, dv -1 + LE mirror) = RBCTL_OUT1 of that LE, all 16 LEs.
- P2: clock polarity (df -6, dv -30) = tile (dx 32, dy 9): NOT a named bit (no name at (32, 9)).
- P3: control-port cells ena (-8,-30) (-7,-30), aclr (-1,-32) (0,-32) (3,-68), sclr (2,-32) (4,-1) are not
  named bits (RSMUX/RSCNT/ROWCLK sit at other dy).
- Refuted if P1 fails in any LE, or if P2/P3 cells carry a name.

  python3.15t scripts/cycloneiv_blkrba_named.py [--csv ...]     Log tmp/logs/cycloneiv_blkrba_named.log
Output vendor-analysis/altera/inventory/s1b/test2.json
"""
import argparse
import collections
import csv
import json
import logging
import sqlite3
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
import cycloneiv_geom as cg  # noqa: E402
from provenance import evidence_io as eio  # noqa: E402

log = logging.getLogger("cycloneiv_blkrba_named")
S1 = REPO / "vendor-analysis/altera/inventory/s1"
OUT = REPO / "vendor-analysis/altera/inventory/s1b"
NV = 6368
LAB_XY = {"a": (10, 10), "b": (58, 30), "c": (37, 60), "d": (100, 75)}


def names_by_pos(path):
    d = collections.defaultdict(list)
    for r in csv.DictReader(open(path)):
        d[(int(r["x_cum"]), int(r["y_cum"]))].append(r["name"])
    return d


def tile_xy(geom, df, dv):
    """(df, dv) from the anchor -> (row_shift, dx, dy) in blkrba tile coordinates."""
    dy = df + 15
    t = 2 - dv
    return t // 70, t % 70, dy


def label(pos, row, dy_ok, nm):
    return nm.get(pos, []) if (row == 0 and dy_ok) else []


def cells_of(blob):
    f = eio.unpack(blob)
    return [(int(i // NV), int(i % NV)) for i in f]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(S1 / "blkrba_stingray_abs.csv"))
    a = ap.parse_args()
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp/logs/cycloneiv_blkrba_named.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    nm = names_by_pos(a.csv)
    geom = cg.load("ep4cgx150")
    res = {}

    # P1: LE-used
    ok = 0
    for le in range(16):
        s = -1 if le % 2 else 1
        dv = geom.DN[le] + s * -1
        row, dx, dy = tile_xy(geom, -8, dv)
        got = nm.get((dx, dy), [])
        want = f"L:{le}:RBCTL_OUT1"
        ok += want in got
        log.info("P1 LE %2d LE-used (-8,%d) -> (dx %d, dy %d) names %s %s", le, dv, dx, dy, got, "OK" if want in got else "MISS")
    log.info("P1: LE-used cell = OUT1 of its LE in %d / 16 LEs", ok)
    res["P1_le_used_out1"] = ok

    # FF pin-select cells (route_learn FF_SEL) and LE-used neighbours, for LE 0..15
    log.info("FF_SEL cells (CLK/ENA (4,2), CLRN (3,2)) per LE:")
    for le in (0, 1, 2, 15):
        s = -1 if le % 2 else 1
        for nme, (df, dv) in (("CLK/ENA", (4, 2)), ("CLRN", (3, 2))):
            row, dx, dy = tile_xy(geom, df, geom.DN[le] + s * dv)
            log.info("  LE %2d %-8s -> (dx %d, dy %d) row %d names %s", le, nme, dx, dy, row, nm.get((dx, dy), []))

    # P2 / P3: LAB-wide cells (no LE offset)
    lab_cells = {"clkpol": [(-6, -30)], "ena": [(-8, -30), (-7, -30)], "aclr": [(-1, -32), (0, -32), (3, -68)],
                 "sclr": [(2, -32), (4, -1)]}
    for k, cl in lab_cells.items():
        for df, dv in cl:
            row, dx, dy = tile_xy(geom, df, dv)
            log.info("P23 %-6s (%d,%d) -> row %d dx %d dy %d names %s", k, df, dv, row, dx, dy, nm.get((dx, dy), []))
    res["lab_cells"] = {k: [list(tile_xy(geom, *c)) for c in cl] for k, cl in lab_cells.items()}

    # measured ctrl diffs from the DB
    con = sqlite3.connect(REPO / "databases/cycloneiv/gx150.db")
    tot = collections.Counter()
    named_hits = collections.Counter()
    per = {}
    for ref, name, rj, bs, bb in con.execute(
            "select source_ref, name, result, bits_spec, bits_base from evidence where source_ref like 'cycloneiv_ctrl:%'"):
        r = json.loads(rj)
        x, y = r["meta"]["xy"]
        f0, v0 = geom.anchor(x, y)
        cells = set(cells_of(bs)) | set(cells_of(bb))
        k = ref.split(":")[1]
        n_in, hits = 0, []
        for f, v in cells:
            dy = f - f0 + 15
            t = v0 + 2 - v
            row, dx = t // 70, t % 70
            if row == 0 and 0 <= dy <= 34:
                n_in += 1
                if nm.get((dx, dy)):
                    hits.append(((dx, dy), nm[(dx, dy)]))
        tot[k, "cells"] += len(cells)
        tot[k, "in_tile"] += n_in
        tot[k, "named"] += len(hits)
        for p, ns in hits:
            named_hits[k, ns[0]] += 1
        per[name] = dict(cells=len(cells), in_tile=n_in, named=[ns[0] for _, ns in hits])
    for k in sorted({k for k, _ in tot}):
        log.info("ctrl %-7s cells %4d, inside own tile %4d, on a named bit %3d, unexplained %4d", k, tot[k, "cells"],
                 tot[k, "in_tile"], tot[k, "named"], tot[k, "cells"] - tot[k, "named"])
    log.info("named bits hit by ctrl diffs (kind, name): count -> %s",
             sorted(((k, n), c) for (k, n), c in named_hits.items())[:60])
    res["ctrl"] = {f"{k}": dict(cells=tot[k, "cells"], in_tile=tot[k, "in_tile"], named=tot[k, "named"])
                   for k in sorted({k for k, _ in tot})}
    res["per_pair"] = per
    # LOCAL_LINE specimen cells (inventory class 3, measured at 4 LABs) vs names
    import cycloneiv_bit_inventory as inv
    rel = None
    for fp, (lx, ly) in zip(inv.FORCED, inv.FORCED_LAB):
        tab = inv.forced_table(fp)
        cur = {(r["src"], r["snk"], r["hop"][4]): {(b // NV - geom.FX[lx], b % NV - (geom.vy0 + 70 * ly)) for b in r["on"]}
               for r in tab.values()}
        if rel is None:
            rel = cur
    universe = sorted({c for p in rel.values() for c in p})
    ll = collections.Counter()
    for df, dv in universe:
        row, dx, dy = tile_xy(geom, df, dv)
        ns = nm.get((dx, dy)) if row == 0 else None
        ll["named" if ns else "unnamed"] += 1
        if ns:
            ll[ns[0].split(":")[-1].rstrip("0123456789")] += 1
    log.info("LL specimen universe %d cells per LAB: %s", len(universe), dict(ll))
    res["ll_universe"] = dict(ll)
    (OUT / "test2.json").write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
