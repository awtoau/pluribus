#!/usr/bin/env python3
"""Trace all config arcs that resolve to the (18,r,307) canonical key for n2803.
Also check at what cols/rows interior tile arcs reference H06W0003/H06E0003 buses."""

import os, sys
sys.path.insert(0, os.environ.get("TRELLIS_BUILD",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("TRELLIS_DBROOT",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database")

from lifters.machxo2_lift import MachXO2Lift

CONFIG = "/mnt/2tb/git/awto-2000/fpga/v7/FPGA_V07.bin.config"
DEVICE = "LCMXO2-1200"

def main():
    lift = MachXO2Lift(DEVICE)
    pc   = lift.parse_config(CONFIG)
    d    = lift.recover_netlist(pc)

    # The canonical key for n2803 pad at R2C21
    target_key = (18, 2, 307)
    target_net = d.net_name.get(d.dsu.find(target_key))
    print(f"Target: {target_key}  net={target_net}")

    # Find ALL arcs where either side resolves to target_key
    print(f"\nAll arcs where gkey == {target_key}:")
    matches = []
    for (r, c, sink, source) in pc.arcs:
        ks = lift.gkey(r, c, sink)
        kd = lift.gkey(r, c, source)
        if ks == target_key or kd == target_key:
            matches.append((r, c, sink, source, ks, kd))

    print(f"  {len(matches)} arcs found:")
    for r, c, sink, source, ks, kd in sorted(matches, key=lambda x: (x[0], x[1])):
        print(f"  R{r}C{c}: {source} -> {sink}  ks={ks}  kd={kd}")

    # Also: scan H06W bus names at various col positions to see which ones
    # resolve to the same canonical as H06E0003 at col=21
    print(f"\nH06W/H06E bus names across columns (row=2):")
    target_row = 2
    for col in range(15, 22):
        for name in ["H06W0003", "W3_H06W0003", "E3_H06E0003", "H06E0003",
                     "H06W0103", "W3_H06W0103"]:
            k = lift.gkey(target_row, col, name)
            if k == target_key:
                print(f"  col={col} '{name}' -> {k} MATCH!")
            elif k:
                pass  # not printing non-matches for brevity

    # Also look at row=4 for n2808 (pin69 at R4C21)
    target_key2 = (18, 4, 307)
    target_net2 = d.net_name.get(d.dsu.find(target_key2))
    print(f"\nTarget2: {target_key2}  net={target_net2}")
    print(f"DSU class size for n2808: ", end="")
    all_in_class = [k for k in d.dsu.p if d.dsu.find(k) == d.dsu.find(target_key2)]
    print(len(all_in_class))
    for k in all_in_class:
        print(f"  {k}")

    # Find arcs where gkey == target_key2
    print(f"\nAll arcs where gkey == {target_key2}:")
    matches2 = []
    for (r, c, sink, source) in pc.arcs:
        ks = lift.gkey(r, c, sink)
        kd = lift.gkey(r, c, source)
        if ks == target_key2 or kd == target_key2:
            matches2.append((r, c, sink, source, ks, kd))
    print(f"  {len(matches2)} arcs found:")
    for r, c, sink, source, ks, kd in sorted(matches2, key=lambda x: (x[0], x[1])):
        print(f"  R{r}C{c}: {source} -> {sink}  ks={ks}  kd={kd}")

    # Check at col=21 whether there are arcs from interior tiles referencing H06E0003
    print(f"\nArcs referencing 'E3_H06E0003' across all tiles:")
    for (r, c, sink, source) in pc.arcs:
        if sink == "E3_H06E0003" or source == "E3_H06E0003":
            ks = lift.gkey(r, c, sink)
            kd = lift.gkey(r, c, source)
            print(f"  R{r}C{c}: {source} -> {sink}  ks={ks}  kd={kd}")


if __name__ == "__main__":
    main()
