#!/usr/bin/env python3.15t
"""Per-tile table for the EP4CGX150 die map (geo investigation, docs/geo-investigation.md).

  python3.15t scripts/geo_tiles.py --image <path.rbf>
Writes tmp/geo/tiles.json (one row per tile) and tmp/geo/luts.npy (LAB x LE x 16-bit INIT of the image).
Log tmp/logs/geo_tiles.log.  Derived/display data only; nothing here is a source of truth.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts"))
log = logging.getLogger("geo_tiles")
NV = 6368
# specimen LABs (full LOCAL_LINE grid) and LE-output (neighbour) grids; evidence/cycloneiv/*
SPECIMEN = [(10, 10), (58, 30), (37, 60), (100, 75)]
LE_OUT = [(10, 10), (37, 60), (58, 30), (100, 75), (6, 10)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    a = ap.parse_args()
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    (REPO / "tmp/geo").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/geo_tiles.log", "w")])
    import cycloneiv_corpus as cc
    import cycloneiv_geom as cg
    from cycloneiv_le_locate import DK
    g = cg.load("ep4cgx150")
    plane = cc.cram_plane(Path(a.image).read_bytes(), g)
    keys = np.asarray(plane.keys, np.int64)
    f, v = keys // NV, keys % NV
    log.info("plane %s, %d set bits", plane.shape, len(keys))
    xs = sorted(g.kind)
    fx = np.array([g.FX[x] for x in xs])
    # column band: [FX-19, FX+16] (35-wide LAB pitch); bin by the nearest FX at or below f+19
    col = np.searchsorted(fx, f + 19, side="right") - 1
    ok = (col >= 0) & (f >= fx[0] - 19)
    row = (v + 48) // 70            # tile band [VY-68, VY+1]
    ok &= (row >= 0) & (row <= g.ymax) & (v < 6344)
    dens = np.zeros((len(xs), g.ymax + 1), np.int32)
    np.add.at(dens, (col[ok], row[ok]), 1)
    log.info("binned %d of %d set bits to tiles", int(ok.sum()), len(keys))

    # LUT INIT vectors for every LAB tile
    labs = [(x, y) for x in xs if g.kind[x] == "LAB" for y in range(1, g.ymax)]
    luts = np.zeros((len(labs), 16), np.uint16)
    for i, (x, y) in enumerate(labs):
        for le in range(16):
            fx0, vy = g.FX[x], g.vy0 + g.vpitch * y
            sg = -1 if le % 2 else 1
            v0 = vy + g.DN[le]
            val = 0
            for b, (df, dv) in enumerate(DK):
                if plane.has(np.array([fx0 + df]), np.array([v0 + sg * dv]))[0]:
                    val |= 1 << b
            luts[i, le] = val
    np.save(REPO / "tmp/geo/luts.npy", luts)
    log.info("luts: %d LABs, %d non-zero INITs", len(labs), int((luts > 0).sum()))

    lab_set = set(labs)
    rows = []
    for ci, x in enumerate(xs):
        w = (fx[ci + 1] - fx[ci]) if ci + 1 < len(xs) else 35
        for y in range(0, g.ymax + 1):
            kind = g.kind[x]
            if y in (0, g.ymax) and kind == "LAB":
                kind = "IOROW"
            cells = int(w * 70)
            ver = 256 if (x, y) in lab_set else 0
            if (x, y) in SPECIMEN:
                tier = "evidence"
            elif (x, y) in lab_set:
                tier = "verified"
            else:
                tier = "unknown"
            rows.append({"x": x, "y": y, "kind": kind, "tier": tier, "cells": cells, "ver": ver,
                         "set": int(dens[ci, y]), "edge": int(x in (0, xs[-1]) or y in (0, g.ymax)),
                         "spec": int((x, y) in SPECIMEN), "leout": int((x, y) in LE_OUT)})
    json.dump({"die": "EP4CGX150", "xmax": g.xmax, "ymax": g.ymax, "tiles": rows},
              open(REPO / "tmp/geo/tiles.json", "w"))
    log.info("tiles %d", len(rows))


if __name__ == "__main__":
    main()
