#!/usr/bin/env python3
"""Diagnose pads with net_in but no net_fanout.
For each, check what's in the DSU class and whether any LUT/FF in the
structural netlist uses that net as an input pin.

FINDING (V07, 2026-07-14): pin75/ADC_D0A net n2803 DSU class contains
(18,3,6111) = SLICEB.FF1.M at R3C18 — the FF's LUT-bypass data input.
recover_netlist() only reads pins["M"] when the slice REG{j}.SD enum is
"1"; when SD is absent/0 it takes pins["DI"] (LUT-output path) and the
routed M wire is silently dropped.  The pad IS connected — the lifter's
FF D-input recovery misses the M path.  Same likely applies to the other
unstitched ADC pads (pin86 class contains SLICEB.FF1.Q at R3C11)."""

import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("TRELLIS_BUILD",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build")
os.environ.setdefault("TRELLIS_DBROOT",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database")

import db, schema
from sqlalchemy import select, func, text

def main():
    conn = db.engine().connect()
    nf = schema.net_fanout
    pm = schema.pad_map

    # Find the 5 unstitched pads
    unstitched = conn.execute(
        select(pm.c.pin, pm.c.net_in, pm.c.label, pm.c.direction, pm.c.row, pm.c.col)
        .where(pm.c.bitstream == 1)
        .where(pm.c.direction.in_(["in", "bidir"]))
        .where(pm.c.net_in.isnot(None))
        .where(
            ~select(nf.c.id)
            .where(nf.c.bitstream == pm.c.bitstream)
            .where(nf.c.net == pm.c.net_in)
            .correlate(pm)
            .exists()
        )
    ).fetchall()

    print(f"=== {len(unstitched)} pads with net_in but no net_fanout ===\n")
    for row in unstitched:
        print(f"pin={row.pin:3d}  R{row.row}C{row.col}  {row.direction:6s}  net={row.net_in}  label={row.label}")

    print()

    # Now check: does the net appear ANYWHERE in net_fanout (as source or
    # destination) to understand why it doesn't drive anything?
    print("=== net_fanout lookup for each net ===\n")
    for row in unstitched:
        net = row.net_in
        # check as driver (net column)
        as_driver = conn.execute(
            select(func.count()).where(nf.c.bitstream == 1).where(nf.c.net == net)
        ).scalar()
        # check as output (out_net column)
        as_output = conn.execute(
            select(func.count()).where(nf.c.bitstream == 1).where(nf.c.out_net == net)
        ).scalar()
        print(f"pin={row.pin} net={net}: as_driver={as_driver}  as_output={as_output}")

    # conn.close() — SQLAlchemy context-managed, just let it go

    # Now recover the structural netlist to check DSU class membership
    print("\n=== Structural netlist check ===\n")
    from lifters.machxo2_lift import MachXO2Lift

    CONFIG = "/mnt/2tb/git/awto-2000/fpga/v7/FPGA_V07.bin.config"
    DEVICE = "LCMXO2-1200"
    lift = MachXO2Lift(DEVICE)
    pc   = lift.parse_config(CONFIG)
    d    = lift.recover_netlist(pc)

    # For each unstitched pad, find what net name the pad gets from the netlist
    target_nets = [row.net_in for row in unstitched]

    # Show DSU class for each
    for row in unstitched:
        net = row.net_in
        # Find the root for this net name
        root = None
        for k, n in d.net_name.items():
            if n == net:
                root = k
                break
        if root is None:
            print(f"pin={row.pin} net={net}: NOT FOUND in netlist net_name!")
            continue
        # Get DSU class
        dsu_class = sorted([k for k in d.dsu.p if d.dsu.find(k) == root])
        print(f"pin={row.pin} net={net}: DSU class size={len(dsu_class)}")
        for k in dsu_class:
            print(f"  {k}")

        # Check if any LUT in design has this net as input
        lut_uses = [(lt["name"], pin, lt["z"])
                    for lt in d.luts
                    for pin in ("a","b","c","d")
                    if lt.get(pin) == net]
        print(f"  LUT uses as input: {len(lut_uses)}")
        for lname, pin, z in lut_uses[:5]:
            print(f"    {lname} pin={pin} z={z}")

        # Check if any FF in design has this net as D/CLK/CE/LSR
        ff_uses = [(ff["name"], pin)
                   for ff in d.ffs
                   for pin, net_attr in (("D","d"),("CLK","clk"),("CE","ce"),("LSR","lsr"))
                   if ff.get(net_attr) == net]
        print(f"  FF uses as input: {len(ff_uses)}")
        for fname, pin in ff_uses[:5]:
            print(f"    {fname} pin={pin}")
        print()

    # Check bels_of() for the (18,3,6111) key specifically
    print("=== bels_of check for R3C18 (pin75 / ADC_D0A) ===\n")
    bels = lift.bels_of(3, 18)
    for bname, pins in sorted(bels.items()):
        for pname, pkey in sorted(pins.items()):
            if pkey is not None and pkey[0] == 18 and pkey[1] == 3:
                print(f"  {bname}.{pname} -> {pkey}")

    # Check what bel pin has canonical (18,3,6111)
    TARGET = (18, 3, 6111)
    print(f"\nBel pin with canonical {TARGET}:")
    for bname, pins in bels.items():
        for pname, pkey in pins.items():
            if pkey == TARGET:
                print(f"  Found: {bname}.{pname}")

if __name__ == "__main__":
    main()
