#!/usr/bin/env python3
"""Diagnostic: trace why 4 right-edge ADC input pads have no net_fanout.

Checks what arcs exist in PIC_R tiles for the failing pads and whether
gkey() can resolve their H06E wires.  Prints per-arc resolution results.
"""

import os
import sys
import re

sys.path.insert(0, os.environ.get("TRELLIS_BUILD",
                                   "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("TRELLIS_DBROOT",
                      "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database")

import db as db_mod
import schema

from lifters.machxo2_lift import MachXO2Lift
from sqlalchemy import select, text

BOARD = "boards/aw2-2d82auto"
DEVICE = "LCMXO2-1200"
PACKAGE = "TQFP100"
LABEL = "V07"

# Failing pads by pin number
FAILING_PINS = {69, 75, 86, 97}

def main():
    config_path = "/mnt/2tb/git/awto-2000/fpga/v7/FPGA_V07.bin.config"

    lift = MachXO2Lift(DEVICE)
    pc   = lift.parse_config(config_path)

    max_col = lift.chip.get_max_col()
    max_row = lift.chip.get_max_row()
    print(f"Device: {DEVICE}  max_col={max_col}  max_row={max_row}")

    # Load pad_map from DB to find row/col for failing pins
    from sqlalchemy import text as _text
    eng = db_mod.engine()
    with eng.connect() as conn:
        row = conn.execute(_text("SELECT id FROM bitstreams WHERE label = :l"),
                           {"l": LABEL}).fetchone()
        if not row:
            print(f"No bitstream with label {LABEL}")
            return
        bs_id = row[0]
        failing_pads = conn.execute(
            _text("SELECT pin, row, col, pio, direction, net_in "
                  "FROM pad_map WHERE bitstream = :b AND pin = ANY(:pins)"),
            {"b": bs_id, "pins": list(FAILING_PINS)}
        ).fetchall()

    print(f"\nFailing pad info:")
    for pin, p_row, p_col, p_pio, p_dir, net_in in failing_pads:
        print(f"  pin{pin:3d}  R{p_row}C{p_col} PIO{p_pio}  dir={p_dir}  net_in={net_in}")

    # For each failing pad, look at arcs in its PIC_R tile
    print(f"\nArc analysis for PIC_R tiles of failing pads:")
    for pin, p_row, p_col, p_pio, p_dir, net_in in failing_pads:
        pio_idx = ord(p_pio) - ord("A")
        jq_name = f"JQ{pio_idx}"
        print(f"\n--- pin{pin} R{p_row}C{p_col} PIO{p_pio} ({jq_name}) ---")

        # Find all arcs at (p_row, p_col) in pc.arcs
        tile_arcs = [(sink, src) for (r, c, sink, src) in pc.arcs
                     if r == p_row and c == p_col]

        if not tile_arcs:
            print("  No arcs in this tile at all!")
            # Check all tiles at this row
            other_rows = sorted(set(r for (r, c, s, src) in pc.arcs if c == p_col))
            print(f"  Rows with arcs at col={p_col}: {other_rows}")
            continue

        print(f"  {len(tile_arcs)} total arcs in this tile")

        # Find arcs where JQ{pio_idx} appears as source (pad input → fabric)
        jq_arcs = [(sink, src) for (sink, src) in tile_arcs
                   if src == jq_name or sink == jq_name]
        print(f"  Arcs referencing {jq_name}: {len(jq_arcs)}")

        for sink, src in jq_arcs:
            ks = lift.gkey(p_row, p_col, sink)
            kd = lift.gkey(p_row, p_col, src)
            print(f"    arc: {sink} {src}")
            print(f"      gkey(sink={sink!r}) = {ks}")
            print(f"      gkey(src={src!r})   = {kd}")

        # Also show the first 10 arcs where gkey fails for either side
        fail_arcs = [(sink, src) for (sink, src) in tile_arcs
                     if lift.gkey(p_row, p_col, sink) is None
                     or lift.gkey(p_row, p_col, src) is None]
        print(f"  Arcs with gkey failures: {len(fail_arcs)} / {len(tile_arcs)}")
        for sink, src in fail_arcs[:10]:
            ks = lift.gkey(p_row, p_col, sink)
            kd = lift.gkey(p_row, p_col, src)
            print(f"    arc: {sink} {src}  ->  sink_key={ks}  src_key={kd}")

        # Try globalise on the raw JQ wire from this tile
        jq_key = lift.gkey(p_row, p_col, jq_name)
        print(f"  gkey({jq_name!r}) from tile R{p_row}C{p_col} = {jq_key}")

        # Also try pad_fabric_node
        pfn = lift.pad_fabric_node(p_row, p_col, p_pio, "in")
        print(f"  pad_fabric_node(R{p_row}C{p_col}, {p_pio!r}, 'in') = {pfn}")

    # Check what H06E/H06W arc names appear at right-edge tiles (col=max_col)
    print(f"\n=== H06E/H06W arc names at col={max_col} ===")
    h06_arcs = set()
    for (r, c, sink, src) in pc.arcs:
        if c != max_col:
            continue
        for name in (sink, src):
            if "H06" in name:
                h06_arcs.add(name)
    for name in sorted(h06_arcs):
        k = lift.gkey(0, max_col, name)  # try row 0 as representative
        print(f"  {name!r}  -> gkey(row=0, col={max_col}) = {k}")
        if k is None:
            # Also try the mirror
            mirror = lift._mirror_e_h06e(name)
            print(f"    mirror = {mirror!r}")
            if mirror:
                gm = lift.rg.globalise_net(0, max_col, mirror)
                print(f"    globalise_net(mirror) = loc({gm.loc.x},{gm.loc.y}) id={gm.id}")


if __name__ == "__main__":
    main()
