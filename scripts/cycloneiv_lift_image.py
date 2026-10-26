#!/usr/bin/env python3.15t
"""Lift a Cyclone IV GX150 .rbf (read in place, never copied) and report the counts.

Reports: used LEs, LUTs, FFs, unresolved LUT inputs, NOT LIFTED classes, driven nets with no reader.
LEs available on the die: 149,760.  Verilog goes to tmp/lift_image/<tag>.v (not tracked).

  python3.15t scripts/cycloneiv_lift_image.py --image PATH --tables tmp/cycloneiv/rl_gx_m8f.json [--tag t]
Log tmp/logs/cycloneiv_lift_image.log; run under a memory-capped scope.
"""
import argparse
import collections
import logging
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in (REPO / "scripts", REPO / "lifters"):
    sys.path.insert(0, str(p))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_emit as em  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_lift as cl  # noqa: E402

log = logging.getLogger("cycloneiv_lift_image")
LE_TOTAL = 149_760


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True)
    ap.add_argument("--tables", default=str(REPO / "tmp" / "cycloneiv" / "rl_gx_m8f.json"))
    ap.add_argument("--tag", default="image")
    ap.add_argument("--max-tiles", type=int, default=0, help="debug: first N LAB tiles only")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    (REPO / "tmp" / "lift_image").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_lift_image.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    lift = cl.CycloneIVLift(cg.die_of("EP4CGX150"), a.tables.split(","))
    plane = cc.cram_plane(Path(a.image).read_bytes(), lift.geom)
    log.info("plane: %d set bits", len(plane))
    tiles = [(x, y) for x in sorted(lift.geom.kind) if lift.geom.kind[x] == "LAB" for y in range(1, lift.geom.ymax)]
    if a.max_tiles:
        tiles = tiles[:a.max_tiles]
    t0 = time.time()
    des = lift.lift(plane, tiles=tiles)
    log.info("lift %.0f s", time.time() - t0)
    v = em.emit(des)
    out = REPO / "tmp" / "lift_image" / f"{a.tag}.v"
    out.write_text(v)
    # nets read vs driven (name-level, from the emitted text)
    drv = set(re.findall(r"^\s*(?:wire|reg)\s+(\S+?)\s*[;=]", v, re.M))
    log.info("used LEs %d (%.1f%% of %d), LUTs %d, FFs %d", des.used_les, 100 * des.used_les / LE_TOTAL, LE_TOTAL,
             len(des.luts), len(des.ffs))
    why = collections.Counter(w for _n, _p, w in des.unresolved)
    log.info("unresolved LUT inputs (mask-dependent): %d", len(des.unresolved))
    for k, n in why.most_common(8):
        log.info("  %-40s %d", k, n)
    for k, n in des.not_lifted.items():
        log.info("NOT LIFTED %s: %d", k, n)
    nin = sum(1 for _ in des.terminals)
    log.info("terminal nets: %d; Verilog %s (%d bytes, %d declared nets)", nin, out.name, len(v), len(drv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
