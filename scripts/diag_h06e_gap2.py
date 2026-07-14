#!/usr/bin/env python3
"""Deeper diagnostic: why do n2803 / n2808 have no net_fanout despite H06E resolving?

Check: after recover_netlist, what DSU root does JQ0 at col=21 get?
And does any LUT's bel pin share that DSU root?
"""

import os, sys
sys.path.insert(0, os.environ.get("TRELLIS_BUILD",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("TRELLIS_DBROOT",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database")

from lifters.machxo2_lift import MachXO2Lift
from sqlalchemy import text as _text
import db as db_mod

CONFIG = "/mnt/2tb/git/awto-2000/fpga/v7/FPGA_V07.bin.config"
DEVICE = "LCMXO2-1200"
LABEL  = "V07"

# Failing right-edge pads by (row, col, pio)
FAILING_PAD_SITES = [(2, 21, "A"), (4, 21, "A")]  # pins 75, 69

def main():
    lift = MachXO2Lift(DEVICE)
    pc   = lift.parse_config(CONFIG)
    d    = lift.recover_netlist(pc)

    max_col = lift.chip.get_max_col()

    for (p_row, p_col, p_pio) in FAILING_PAD_SITES:
        pio_idx = ord(p_pio) - ord("A")
        jq_name = f"JQ{pio_idx}"

        # The canonical key gkey() gives for JQ at this PIC_R tile
        jq_key = lift.pad_fabric_node(p_row, p_col, p_pio, "in")
        print(f"\n--- R{p_row}C{p_col} PIO{p_pio} ({jq_name}) ---")
        print(f"  pad_fabric_node key = {jq_key}")

        if jq_key is None:
            print("  pad_fabric_node returned None!")
            continue

        if jq_key not in d.dsu.p:
            print("  JQ key NOT in DSU at all (pad arc never processed?)")
            # Check if we can find the gkey directly from arcs at this tile
            tile_arcs = [(s, src) for (r, c, s, src) in pc.arcs
                         if r == p_row and c == p_col]
            print(f"  Arcs in tile: {tile_arcs}")
            continue

        root = d.dsu.find(jq_key)
        net  = d.net_name.get(root)
        print(f"  DSU root = {root}")
        print(f"  Net name = {net}")

        # How many other keys share this DSU root?
        all_in_class = [k for k in d.dsu.p if d.dsu.find(k) == root]
        print(f"  DSU class size: {len(all_in_class)} keys")
        if len(all_in_class) <= 20:
            for k in all_in_class:
                print(f"    {k}")

        # Do any LUTs have this net as an input?
        luts_using = [lt for lt in d.luts
                      if net in (lt["a"], lt["b"], lt["c"], lt["d"])]
        print(f"  LUTs using {net} as input: {len(luts_using)}")
        for lt in luts_using[:5]:
            print(f"    {lt['name']}  a={lt['a']} b={lt['b']} c={lt['c']} d={lt['d']} z={lt['z']}")

        # Does this net appear as a FF D input?
        ffs_using = [ff for ff in d.ffs if ff["d"] == net]
        print(f"  FFs with D={net}: {len(ffs_using)}")

        # Is the key in src_keys? (i.e., is it a net that drives something)
        # src_keys is internal to recover_netlist; approximate by checking
        # if the root is in d.used_roots
        print(f"  In d.used_roots: {root in d.used_roots}")

        # Also look for what the H06E0003 wire canonical is
        h06e_key = lift.gkey(p_row, p_col, "E3_H06E0003")
        h06e_root = d.dsu.find(h06e_key) if (h06e_key and h06e_key in d.dsu.p) else None
        print(f"  H06E0003 key={h06e_key}  root={h06e_root}")

        # Are JQ0 and H06E0003 in the same DSU class?
        if h06e_key and h06e_key in d.dsu.p:
            same_class = (root == h06e_root)
            print(f"  JQ0 and H06E0003 in same DSU class: {same_class}")

    # For top-edge pads (pins 97, 86)
    print("\n=== TOP-EDGE PADS (row=0) ===")
    for (p_row, p_col, p_pio) in [(0, 9, "A"), (0, 11, "C")]:
        pio_idx = ord(p_pio) - ord("A")
        jq_name = f"JQ{pio_idx}"
        print(f"\n--- R{p_row}C{p_col} PIO{p_pio} ({jq_name}) ---")

        # What does pad_fabric_node return for top-edge?
        pfn = lift.pad_fabric_node(p_row, p_col, p_pio, "in")
        print(f"  pad_fabric_node = {pfn}")

        # What arcs exist at (row=0, col=...) vs (row=1, col=...)
        r0_arcs = [(s, src) for (r, c, s, src) in pc.arcs
                   if r == 0 and c == p_col]
        r1_arcs = [(s, src) for (r, c, s, src) in pc.arcs
                   if r == 1 and c == p_col]
        print(f"  Arcs at R0C{p_col}: {len(r0_arcs)}")
        print(f"  Arcs at R1C{p_col}: {len(r1_arcs)}")

        # Look for JQ-related arcs at row=1 (CIB row below top-edge PIC)
        jq_arcs_r1 = [(s, src) for (s, src) in r1_arcs
                      if jq_name in (s, src)]
        print(f"  Arcs at R1C{p_col} referencing {jq_name}: {jq_arcs_r1}")

        # Look for any arc at row=0 that involves any JQ wire
        jq_all = [(s, src) for (s, src) in r0_arcs
                  if "JQ" in s or "JQ" in src]
        print(f"  JQ arcs at R0C{p_col}: {jq_all}")

        # Check tile type
        ttype_r0 = pc.tile_type.get((0, p_col), "?")
        ttype_r1 = pc.tile_type.get((1, p_col), "?")
        print(f"  Tile type R0C{p_col}: {ttype_r0}")
        print(f"  Tile type R1C{p_col}: {ttype_r1}")

        # If row=1 arcs reference JQ, trace what gkey gives
        for s, src in jq_arcs_r1:
            ks = lift.gkey(1, p_col, s)
            kd = lift.gkey(1, p_col, src)
            print(f"    arc: {s} {src}  ks={ks}  kd={kd}")

        # Check if the pad_fabric_node key IS in the DSU
        if pfn:
            in_dsu = pfn in d.dsu.p
            net = d.net_name.get(d.dsu.find(pfn)) if in_dsu else None
            print(f"  pfn in DSU: {in_dsu}  net={net}")
        else:
            print(f"  pad_fabric_node returned None → pad net not recovered")


if __name__ == "__main__":
    main()
