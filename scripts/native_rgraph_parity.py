#!/usr/bin/env python3.15t
"""Parity-check the native routing-graph port against the pytrellis golden.

The golden is produced by scripts/native_rgraph_golden.py (which needs the
pytrellis .so, run once).  This checker needs NO .so -- it validates the pure
Python port, stage by stage.

    python3.15t scripts/native_rgraph_parity.py [GOLDEN.json]

Exit 0 iff every checked stage matches exactly.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
# Native parity needs only the text tile DB (no .so); repo-local fallback.
DBROOT = os.environ.get(
    "TRELLIS_DBROOT", os.path.join(REPO, "tmp/prjtrellis/database"))

import re  # noqa: E402
from native_trellis.geometry import ChipGeometry  # noqa: E402
from native_trellis.globalise import Globaliser  # noqa: E402
from native_trellis.rgraph import NativeRoutingGraph  # noqa: E402

_LUTIN = re.compile(r"^[A-D][0-7]$")
_LUTIN_SLICE = re.compile(r"^[A-D][0-7]_SLICE$")


def _is_lutperm(a):
    """golden arc [sx,sy,sname,dx,dy,dname,cfg] that is a LUT-perm crossbar pip.

    Crossbar pips are `Xk -> Yk_SLICE` with X != Y (different letter) and the
    SAME digit k (Chip.cpp:355-370, i != j).  Real `.fixed_conn Xk_SLICE Xk`
    arcs look similar but keep the SAME letter -- must NOT be excluded.
    """
    sx, sy, sname, dx, dy, dname, cfg = a
    return (not cfg and sx == dx and sy == dy
            and _LUTIN.match(sname) and _LUTIN_SLICE.match(dname)
            and sname[0] != dname[0] and sname[1] == dname[1])


def check_geometry(g, geom):
    fails = []
    if geom.max_row != g["max_row"]:
        fails.append(f"max_row {geom.max_row} != {g['max_row']}")
    if geom.max_col != g["max_col"]:
        fails.append(f"max_col {geom.max_col} != {g['max_col']}")
    # tile_rc: golden values are [row, col]
    gold_rc = {k: tuple(v) for k, v in g["tile_rc"].items()}
    for name, rc in gold_rc.items():
        got = geom.tile_rc.get(name)
        if got != rc:
            fails.append(f"tile_rc[{name}] {got} != {rc}")
    # native must not invent tiles the golden lacks (for names golden covers)
    extra = set(geom.tile_rc) - set(gold_rc)
    # golden tile_rc only holds tiles reachable via get_tiles_by_position; the
    # native map holds every tilegrid entry.  Only flag position disagreements,
    # not presence, so `extra` is informational.
    return fails, len(gold_rc), len(extra)


def check_globalise(g, gl):
    """Native globalise_net vs golden raw-name table (loc "x,y" -> {name: [x,y,id] | null})."""
    fails = []
    total = 0
    for key, gm in g["globalise"].items():
        col, row = map(int, key.split(","))
        for name, exp in gm.items():
            total += 1
            got = gl.globalise_net(row, col, name)
            got_l = None if got is None else [got.x, got.y, got.name]
            if got_l != exp:
                fails.append(f"glob({row},{col},{name}) native={got_l} golden={exp}")
    return fails, total


def main():
    golden = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        REPO, "tmp", "rgraph_golden_LCMXO2-1200.json")
    g = json.load(open(golden))
    device = g["chip"]
    geom = ChipGeometry(device, DBROOT, g["family"])

    print(f"=== Stage B: geometry parity ({device}) ===")
    fails, ntiles, nextra = check_geometry(g, geom)
    if fails:
        print(f"  FAIL ({len(fails)} mismatches of {ntiles} golden tiles):")
        for f in fails[:20]:
            print(f"    {f}")
        return 1
    print(f"  OK  max_row={geom.max_row} max_col={geom.max_col}  "
          f"tile_rc: {ntiles}/{ntiles} match  "
          f"(native has {nextra} extra tilegrid entries not in golden rc)")

    print(f"=== Stage C: globalise_net parity ({device}) ===")
    gl = Globaliser(device, geom.max_row, geom.max_col)
    gfails, gtotal = check_globalise(g, gl)
    if gfails:
        print(f"  FAIL ({len(gfails)} mismatches of {gtotal} globalise calls):")
        for f in gfails[:25]:
            print(f"    {f}")
        return 1
    print(f"  OK  globalise_net: {gtotal}/{gtotal} raw db-names match exactly")

    print(f"=== Stage D: wires / arcs / SLICE bels parity ({device}) ===")
    rg = NativeRoutingGraph(device, DBROOT, g["family"])
    rc = check_stage_d(g, rg)
    if rc:
        return 1
    return 0


def check_stage_d(g, rg):
    # --- arcs: native add_routing arcs must equal golden arcs minus LUT-perm --
    arc_fail = 0
    native_extra = 0
    lut_leftover_bad = 0
    for key, loc in g["locs"].items():
        col, row = map(int, key.split(","))
        gold = set()
        gold_lut = 0
        for a in loc["arcs"]:
            if _is_lutperm(a):
                gold_lut += 1
                continue
            gold.add((a[0], a[1], a[2], a[3], a[4], a[5], bool(a[6])))
        nat = set()
        for arc in rg.arcs.get((col, row), []):
            nat.add((arc.src.x, arc.src.y, arc.src.name,
                     arc.sink.x, arc.sink.y, arc.sink.name, arc.configurable))
        if nat != gold:
            if arc_fail < 8:
                miss = gold - nat
                extra = nat - gold
                print(f"  ARC MISMATCH @{key}: "
                      f"golden-only={len(miss)} native-only={len(extra)}")
                for m in list(miss)[:3]:
                    print(f"      golden-only {m}")
                for e in list(extra)[:3]:
                    print(f"      native-only {e}")
            arc_fail += 1

    # --- SLICE bels: exact (name,type,z,pins x/y/name) ----------------------
    bel_fail = 0
    nbel = 0
    for key, loc in g["locs"].items():
        col, row = map(int, key.split(","))
        nat_bels = rg.bels.get((col, row), {})
        for bn, gb in loc["bels"].items():
            if not bn.startswith("SLICE"):
                continue
            nbel += 1
            nb = nat_bels.get(bn)
            if nb is None:
                bel_fail += 1
                if bel_fail <= 6:
                    print(f"  BEL MISSING @{key} {bn}")
                continue
            gp = {p: (v[0], v[1], v[2]) for p, v in gb["pins"].items()}
            npn = {p: (r.x, r.y, r.name) for p, r in nb.pins.items()}
            if nb.type != gb["type"] or nb.z != gb["z"] or npn != gp:
                bel_fail += 1
                if bel_fail <= 6:
                    print(f"  BEL MISMATCH @{key} {bn}: "
                          f"type {nb.type}/{gb['type']} z {nb.z}/{gb['z']} "
                          f"pins_eq={npn == gp}")

    # --- wire set: native must be subset of golden (golden also has non-SLICE
    #     bel wires the lifter never reads) --------------------------------
    wire_notin = 0
    golden_only_total = 0
    for key, loc in g["locs"].items():
        col, row = map(int, key.split(","))
        gold = set(loc["wires"])
        nat = rg.wires.get((col, row), set())
        missing = nat - gold          # native wire absent from golden -> BUG
        wire_notin += len(missing)
        golden_only_total += len(gold - nat)
        if missing and wire_notin <= 20:
            print(f"  WIRE native-only @{key}: {sorted(missing)[:6]}")

    ok = (arc_fail == 0 and bel_fail == 0 and wire_notin == 0)
    print(f"  arcs: {'OK' if arc_fail == 0 else f'FAIL ({arc_fail} locs)'}  "
          f"(golden LUT-perm pips excluded)")
    print(f"  SLICE bels: {'OK' if bel_fail == 0 else f'FAIL ({bel_fail})'}  "
          f"({nbel} checked)")
    print(f"  wires: {'OK' if wire_notin == 0 else f'FAIL ({wire_notin} native-only)'}"
          f"  (native subset of golden; {golden_only_total} golden non-SLICE-bel "
          f"wires unused by lifter)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
