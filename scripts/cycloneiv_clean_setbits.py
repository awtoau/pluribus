#!/usr/bin/env python3
"""Ground-truth-free lift metric: fraction of SET bits explained, by tier and block, for corpus designs and one third-party image (#165, #169).

  python3.15t scripts/cycloneiv_clean_setbits.py [--n 20]     # image from env PLURIBUS_DJI_IMAGE only; log tmp/logs/cycloneiv_clean_setbits.log,
                                                              # json tmp/cycloneiv_clean/setbits.json (counts only)

Tiers (a set plane cell belongs to exactly one):
  A validated   LUT INIT (1a), routing pips under the vendor rule (8g) and clock network (8c) - gate/oracle-scored classes - and IO CFF pair-measured (9a)
  B decoded     group decoded, no oracle: clock select (8a), register-used (8b), IO CFF sampled / decoded (9b, 9c)
  C address-only  placed group, meaning not decoded: other LAB groups (8d), M9K (8e), MAC (8f); option bits not in a decoded group
  D residue     CRAM cell in no class, inside a column tile
  E edge        CRAM cell in no class in pre-column frames / IO bands; periphery cells (frames 1..36) that carry no CFF bit or a CFF bit no group names
Class cell sets: scripts/cycloneiv_clean_classes.build (vendor group bits).  Design set cells: cycloneiv_corpus.cram_plane (frames 1.., header excluded).
A tier bit is "placed by a validated decoder", not "proven correct": the calibration table sets it beside the gate match rate.
"""
import argparse
import json
import logging
import os
import sys

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import plane as P  # noqa: E402
import cycloneiv_clean_classes as C  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_setbits.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "setbits.json")
GATE = os.path.join(REPO, "tmp", "cycloneiv_clean", "gate_rb10_vendor2.json")
GEOM = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_geom.json")
# source: scripts/cycloneiv_clean_classes.py docstring (class meanings); tiers per this script's docstring
TIER_OF = {"1a": "A", "8g": "A", "8c": "A", "9a": "A", "8a": "B", "8b": "B", "9b": "B", "9c": "B", "8d": "C", "8e": "C", "8f": "C", "9d": "C"}
# source: same docstring; block column of the breakdown
BLOCK_OF = {"1a": "LAB", "8a": "LAB", "8b": "LAB", "8d": "LAB", "8e": "M9K", "8f": "MAC", "8g": "routing", "8c": "clock", "9a": "IO", "9b": "IO",
            "9c": "IO", "9d": "IO"}
TIERS = "ABCDE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    log = logging.getLogger("setbits")
    log.setLevel(logging.INFO)
    log.addHandler(logging.FileHandler(LOG, "w"))
    log.addHandler(logging.StreamHandler(sys.stdout))
    geo = cg.load(cg.die_of("EP4CGX150"))
    vmap = cc.vmap_for(P.RBF_FRAME_BYTES, tuple(geo.lane_bytes), tuple(map(tuple, geo.lane_swaps)))
    nv = len(vmap)
    sets, _ = C.build(nv, vmap)
    ncell = 6191 * nv
    tier = np.full(ncell, ord("."), np.uint8)       # tier letter per plane cell, '.' = not classed
    blk = np.zeros(ncell, np.uint8)
    names = ["residue", "LAB", "M9K", "MAC", "routing", "clock", "IO"]
    for cid, cells in sets.items():
        if cid in TIER_OF:
            tier[cells] = ord(TIER_OF[cid])
            blk[cells] = names.index(BLOCK_OF[cid])
    # residue cells -> D (tile) or E (pre-column frames / IO bands / periphery)
    fr = np.arange(ncell, dtype=np.int64) // nv
    vv = np.arange(ncell, dtype=np.int64) % nv
    unclassed = tier == ord(".")
    periph = fr < P.RBF_PRE_FRAMES
    # CRAM plane frame r -> sof frame s = 6153 - r (A5 mirror blocks inside are not undone: they only move cells within 256 frames)
    s = 6153 - (fr - P.RBF_PRE_FRAMES)
    g = json.load(open(GEOM))
    fx0 = min(int(x) for x in g["FX"].values())
    sof_v = 6344 - vv                                  # plane v = 6344 - sof v (P.plane_v)
    in_tile = (sof_v >= 23) & (sof_v <= 6322) & (s >= fx0) & ~periph
    tier[unclassed & in_tile] = ord("D")
    tier[unclassed & ~in_tile] = ord("E")
    designs = [("gx150_rb_%03d" % i) for i in range(10)]
    allc = sorted(d for d in os.listdir(os.path.join(REPO, "corpus", "cycloneiv")) if d.startswith("gx150_rb_"))
    designs += [d for d in allc if d not in designs][: max(0, a.n - 10 - 0)]
    paths = {d: os.path.join(REPO, "corpus", "cycloneiv", d, "bitstream.rbf") for d in designs}
    if os.environ.get("PLURIBUS_DJI_IMAGE"):
        paths["third_party_image"] = os.environ["PLURIBUS_DJI_IMAGE"]
    gate = {r["design"]: r for r in json.load(open(GATE))["rows"]} if os.path.exists(GATE) else {}
    res = {}
    for d, pth in paths.items():
        if not os.path.exists(pth):
            continue
        plane = cc.cram_plane(open(pth, "rb").read(), geo)
        keys = plane.keys
        keys = keys[keys < ncell]
        t = tier[keys]
        b = blk[keys]
        row = {"set_cells": int(len(keys)), "tier": {k: int((t == ord(k)).sum()) for k in TIERS}}
        row["tier"]["periphery_unclassed_E"] = int(((t == ord("E")) & periph[keys]).sum())
        row["block"] = {n: {k: int(((b == i) & (t == ord(k))).sum()) for k in "ABC"} for i, n in enumerate(names) if i}
        tot = max(1, len(keys))
        row["explained_ABC"] = round(100 * sum(row["tier"][k] for k in "ABC") / tot, 2)
        row["validated_A"] = round(100 * row["tier"]["A"] / tot, 2)
        if d in gate:
            def rate(x):
                m = eval(x) if isinstance(x, str) else x
                n = sum(m.values())
                return round(100 * m["matched"] / n, 2) if n else None
            row["gate"] = {k: rate(gate[d][k]) for k in ("pips", "nets", "lut_init", "register_clock")}
        res[d] = row
        log.info("%-18s set %8d  A %7d B %7d C %7d D %7d E %7d  explained %.2f%% validated %.2f%%  gate %s", d, len(keys), *[row["tier"][k] for k in TIERS],
                 row["explained_ABC"], row["validated_A"], row.get("gate"))
    json.dump(res, open(OUT, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
