#!/usr/bin/env python3.15t
"""Dump the *static* pytrellis routing graph for a MachXO2 device to JSON.

This is the GROUND TRUTH for the native routing-graph port (issue: drop the
pytrellis .so).  The routing graph does not depend on any bitstream -- it is a
pure function of the device -- so a single exhaustive dump lets the native
reimplementation be parity-checked against every tile, wire, bel and every
`globalise_net` result.

Run under python3.15t with a free-threaded pytrellis build on the path:

    TRELLIS_BUILD=<fork>/libtrellis/build_315 \\
    TRELLIS_DBROOT=<fork>/database \\
    python3.15t scripts/native_rgraph_golden.py [DEVICE] [OUT.json]

Defaults: DEVICE=LCMXO2-1200, OUT=tmp/rgraph_golden_<device>.json
This is a regenerable validation artefact -- it lives in tmp/, uncommitted.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The pytrellis .so + tile DB (needed only to GENERATE this golden) come from
# TRELLIS_BUILD / TRELLIS_DBROOT; fall back to a repo-local prjtrellis checkout.
BUILD = os.environ.get(
    "TRELLIS_BUILD", os.path.join(REPO, "tmp/prjtrellis/libtrellis/build"))
DBROOT = os.environ.get(
    "TRELLIS_DBROOT", os.path.join(REPO, "tmp/prjtrellis/database"))


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else "LCMXO2-1200"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        REPO, "tmp", f"rgraph_golden_{device}.json")

    sys.path.insert(0, BUILD)
    import pytrellis
    pytrellis.load_database(DBROOT)
    assert not sys._is_gil_enabled(), "GIL got re-enabled -- wrong pytrellis build"

    chip = pytrellis.Chip(device)
    rg = chip.get_routing_graph(True, True)
    ts = rg.to_str

    g = {
        "chip": device,
        "max_row": rg.max_row,
        "max_col": rg.max_col,
        "family": rg.chip_family,
        "tile_rc": {},
        "locs": {},
        "globalise": {},
    }

    # tile full-name -> [row, col] (chip geometry)
    for r in range(chip.get_max_row() + 1):
        for c in range(chip.get_max_col() + 1):
            try:
                tiles = chip.get_tiles_by_position(r, c)
            except Exception:
                tiles = []
            for t in tiles:
                g["tile_rc"][t.info.name] = [r, c]

    # per-location wires / bels / arcs, plus globalise for every wire name
    for loc, t in rg.tiles.items():
        key = f"{loc.x},{loc.y}"
        wire_names = [ts(w.id) for w in t.wires.values()]

        bels = {}
        for bk, bel in t.bels.items():
            pins = {}
            for pid, (wire, pdir) in bel.pins.items():
                pins[ts(pid)] = [wire.loc.x, wire.loc.y, ts(wire.id), int(pdir)]
            bels[ts(bk)] = {"type": ts(bel.type), "z": bel.z, "pins": pins}

        arcs = []
        for _aid, arc in t.arcs.items():
            s, d = arc.source, arc.sink
            arcs.append([s.loc.x, s.loc.y, ts(s.id),
                         d.loc.x, d.loc.y, ts(d.id),
                         bool(arc.configurable)])

        g["locs"][key] = {"wires": wire_names, "bels": bels, "arcs": arcs}

    # globalise golden: the REAL inputs are the raw (relative) db-names from
    # each tile's connectivity DB -- mux sinks/sources + fixed_conn endpoints.
    # For each tile position, globalise every such raw name via pytrellis and
    # record the result so the native port can be parity-checked with no .so.
    sys.path.insert(0, REPO)
    from native_trellis.tiledb import load_tiletype
    family = rg.chip_family
    for r in range(chip.get_max_row() + 1):
        for c in range(chip.get_max_col() + 1):
            for t in chip.get_tiles_by_position(r, c):
                ttype = t.info.type
                muxes, fixed = load_tiletype(DBROOT, family, ttype)
                raw = set(muxes) | {s for ss in muxes.values() for s in ss}
                for sink, src in fixed:
                    raw.add(sink)
                    raw.add(src)
                gm = g["globalise"].setdefault(f"{c},{r}", {})
                for nm in raw:
                    rid = rg.globalise_net(r, c, nm)
                    # RoutingId() default is id == -1 (invalid); to_str(-1)
                    # would throw, so record invalid results as null.
                    gm[nm] = None if rid.id == -1 else [
                        rid.loc.x, rid.loc.y, ts(rid.id)]

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(g, fh)
    nwires = sum(len(v["wires"]) for v in g["locs"].values())
    nbels = sum(len(v["bels"]) for v in g["locs"].values())
    print(f"wrote {out}")
    print(f"  device={device} grid={g['max_row']}x{g['max_col']} "
          f"locs={len(g['locs'])} wires={nwires} bels={nbels} "
          f"tile_rc={len(g['tile_rc'])}")


if __name__ == "__main__":
    raise SystemExit(main())
