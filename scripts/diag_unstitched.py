#!/usr/bin/env python3
"""For each still-unstitched input pad, find all routing arcs in the bitstream
that could carry its signal — checking both the right-edge tile and interior tiles
referencing the H06W bus."""

import os, sys
sys.path.insert(0, os.environ.get("TRELLIS_BUILD",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build"))
sys.path.insert(0, os.path.dirname("/mnt/2tb/git/pluribus/"))
sys.path.insert(0, "/mnt/2tb/git/pluribus")
os.environ.setdefault("TRELLIS_DBROOT",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database")

from lifters.machxo2_lift import MachXO2Lift

CONFIG = "/mnt/2tb/git/awto-2000/fpga/v7/FPGA_V07.bin.config"
DEVICE = "LCMXO2-1200"

# Still-unstitched pads: (pin, row, col, pio)
PADS = [
    (75,  2, 21, "A"),  # ADC_D0A
    (71,  3, 21, "A"),  # ADC_D2A
    (86,  0, 11, "C"),  # ADC_D3B
    (97,  0,  9, "A"),  # ADC_D7B
    (35, 12,  8, "B"),  # DAC_PD (bidir)
]

def main():
    lift = MachXO2Lift(DEVICE)
    pc   = lift.parse_config(CONFIG)
    d    = lift.recover_netlist(pc)
    max_col = lift.chip.get_max_col()
    max_row = lift.chip.get_max_row()
    print(f"Grid: {max_col+1} cols x {max_row+1} rows\n")

    for (pin, p_row, p_col, p_pio) in PADS:
        pio_idx = ord(p_pio) - ord("A")
        jq = f"JQ{pio_idx}"
        pad_key = lift.gkey(p_row, p_col, f"E3_H06E0003") if p_col == max_col else None
        pfn = lift.pad_fabric_node(p_row, p_col, p_pio, "in")

        print(f"=== pin{pin} R{p_row}C{p_col} PIO{p_pio} ({jq}) ===")
        print(f"  pad_fabric_node = {pfn}")

        if pfn:
            root = d.dsu.find(pfn) if pfn in d.dsu.p else None
            net  = d.net_name.get(root) if root else None
            all_keys = [k for k in d.dsu.p if d.dsu.find(k) == root] if root else []
            print(f"  net={net}  DSU class size={len(all_keys)}")
            if len(all_keys) <= 10:
                for k in all_keys:
                    print(f"    {k}")

        # All arcs at this tile
        tile_arcs = [(s, src) for (r,c,s,src) in pc.arcs if r==p_row and c==p_col]
        print(f"  Arcs at R{p_row}C{p_col}: {len(tile_arcs)}")
        for s, src in tile_arcs:
            ks = lift.gkey(p_row, p_col, s)
            kd = lift.gkey(p_row, p_col, src)
            print(f"    arc: {src} -> {s}  kd={kd}  ks={ks}")

        # For right-edge pads: also check all tiles at this row for H06W arcs
        if p_col == max_col:
            print(f"  Interior H06W arcs at row={p_row}:")
            for (r, c, s, src) in pc.arcs:
                if r != p_row:
                    continue
                for name in (s, src):
                    if "H06W" in name or "H06E" in name:
                        ks2 = lift.gkey(r, c, s)
                        kd2 = lift.gkey(r, c, src)
                        print(f"    R{r}C{c}: {src} -> {s}  kd={kd2}  ks={ks2}")
                        break

        print()

if __name__ == "__main__":
    main()
