#!/usr/bin/env python3.15t
"""TEST 3 of the blkrba hypothesis (#165): sampling plan over the LAB array + on/off read-back of the
non-LUT named bits in corpus builds.  Position law from TEST 1 (cycloneiv_blkrba_lab.py); names from the local csv.

PREDICTION (written before the run)
- S1: the 256 LUT cells read back exactly in every LAB class: corners, edges, columns next to M9K / MUL, interior.
- S2: the LE-used bit (RBCTL_OUT1 of the LE) is set in a corpus design iff the LE holds an LCCOMB or FF.
- S3: RBCTL_REG0..3 / IN0 / IN1 / OUT0 / OUT2 are set only in LEs that hold a FF (REG) or a routed LUT (IN/OUT);
  reported as a contingency vs FF present, not as a rule.
Refuted if any LUT mask bit in any sampled LAB differs from the .vo, or S2 has a counter-example.
Tile classes: corner = {x_min,x_max} x {1,90} of the LAB array; edge = any LAB with x or y at the array edge;
nbr = LAB whose column is adjacent to an M9K / MUL / IO column; interior = rest.

  python3.15t scripts/cycloneiv_blkrba_sample.py [--designs 'gx150_*']   Log tmp/logs/cycloneiv_blkrba_sample.log
Output vendor-analysis/altera/inventory/s1b/test3.json
"""
import argparse
import collections
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_blkrba_lab as bl  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402

log = logging.getLogger("cycloneiv_blkrba_sample")
OUT = REPO / "vendor-analysis/altera/inventory/s1b"
LCC = re.compile(r"^LCCOMB_X(\d+)_Y(\d+)_N(\d+)$")
FFL = re.compile(r"^FF_X(\d+)_Y(\d+)_N(\d+)$")


def tile_class(geom, labs_x, x, y):
    ex = x in (labs_x[0], labs_x[-1])
    ey = y in (1, geom.ymax - 1)
    if ex and ey:
        return "corner"
    if ex or ey:
        return "edge"
    if geom.col_kind(x - 1) != "LAB" or geom.col_kind(x + 1) != "LAB":
        return "nbr"
    return "interior"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(bl.DEFAULT_CSV))
    ap.add_argument("--designs", default="gx150_*")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp/logs/cycloneiv_blkrba_sample.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = bl.load_csv(a.csv)
    tab = bl.lut_table(names)
    geom = cg.load("ep4cgx150")
    labs_x = sorted(x for x in geom.FX if geom.col_kind(x) == "LAB")
    c0 = bl.fit_const(tab, geom, "H2")
    out1 = {le: names[f"L:{le}:RBCTL_OUT1"] for le in range(16)}
    other = {n: xy for n, xy in names.items() if re.match(r"^L:\d+:RBCTL_(REG\d|IN\d|OUT[02])$", n)}

    def pos(x, y, xy):
        f0, v0 = geom.anchor(x, y)
        return f0 + xy[1] - c0[0], v0 + c0[1] - xy[0]

    def one(name):
        d = cc.load(name)
        plane = d["plane"]
        sites = collections.defaultdict(lambda: [0, 0])      # (x,y,le) -> [has_lcc, has_ff]
        for at in d["vo"].atoms.values():
            m = LCC.match(at.get("location") or "")
            if m:
                sites[(int(m[1]), int(m[2]), int(m[3]) // 2)][0] = 1
            m = FFL.match(at.get("location") or "")
            if m:
                sites[(int(m[1]), int(m[2]), int(m[3]) // 2)][1] = 1
        lut = collections.Counter()
        s2 = collections.Counter()
        s3 = collections.Counter()
        tiles = set()
        for (x, y, le), (hl, hf) in sites.items():
            if x not in geom.FX or geom.col_kind(x) != "LAB":
                continue
            tiles.add((x, y))
            cls = tile_class(geom, labs_x, x, y)
            f, v = pos(x, y, out1[le])
            s2[(hl or hf, bool(plane[f, v]))] += 1
            for n, xy in other.items():
                if int(n.split(":")[1]) != le:
                    continue
                f, v = pos(x, y, xy)
                s3[(n.split(":")[2], hf, bool(plane[f, v]))] += 1
        for at in d["vo"].atoms.values():
            m = LCC.match(at.get("location") or "")
            if not m:
                continue
            x, y, n = map(int, m.groups())
            if x not in geom.FX or geom.col_kind(x) != "LAB":
                continue
            want = int(at["params"]["lut_mask"].split("'h")[1], 16)
            got = 0
            for k in range(16):
                f, v = pos(x, y, tab[(n // 2, k)])
                got |= int(bool(plane[f, v])) << k
            cls = tile_class(geom, labs_x, x, y)
            lut[cls, "bits_ok"] += 16 - bin(got ^ want).count("1")
            lut[cls, "bits_bad"] += bin(got ^ want).count("1")
            lut[cls, "cells"] += 1
        return tiles, lut, s2, s3

    ds = cc.designs(a.designs)
    tiles_all, lut, s2, s3 = set(), collections.Counter(), collections.Counter(), collections.Counter()
    with ThreadPoolExecutor(a.workers) as ex:
        for t, l, b, c in ex.map(one, ds):
            tiles_all |= t
            lut.update(l)
            s2.update(b)
            s3.update(c)
    cls_tiles = collections.Counter(tile_class(geom, labs_x, x, y) for x, y in tiles_all)
    all_cls = collections.Counter(tile_class(geom, labs_x, x, y) for x in labs_x for y in range(1, geom.ymax)
                                  if (x, y) not in geom.no_lab)
    log.info("designs %d; LABs touched %d of %d; by class touched/all: %s", len(ds), len(tiles_all), sum(all_cls.values()),
             {k: f"{cls_tiles[k]}/{all_cls[k]}" for k in all_cls})
    log.info("corners touched: %s", sorted(t for t in tiles_all if tile_class(geom, labs_x, *t) == "corner"))
    res = {"designs": len(ds), "tiles_touched": len(tiles_all), "class_touched": dict(cls_tiles), "class_all": dict(all_cls)}
    for cls in all_cls:
        ok, bad, cells = lut[cls, "bits_ok"], lut[cls, "bits_bad"], lut[cls, "cells"]
        log.info("S1 %-8s LUT cells %6d, mask bits matched %8d / (matched + wrong %d)", cls, cells, ok, bad)
        res[f"S1_{cls}"] = [cells, ok, bad]
    log.info("S2 LE-used (OUT1) vs LE holds LCCOMB/FF: %s", {f"site={k[0]},bit={k[1]}": c for k, c in sorted(s2.items())})
    res["S2"] = {f"site={k[0]},bit={k[1]}": c for k, c in s2.items()}
    cont = collections.defaultdict(dict)
    for (nm_, hf, bit), c in s3.items():
        cont[nm_][f"ff={int(hf)},bit={int(bit)}"] = c
    for n in sorted(cont):
        log.info("S3 %-14s %s", n, dict(sorted(cont[n].items())))
    res["S3"] = cont
    (OUT / "test3.json").write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
