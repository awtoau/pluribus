#!/usr/bin/env python3
"""Classify FF D-inputs in a recovered netlist — the health metric for
REG.SD handling in lifters/machxo2_lift.py.

For every FF, its D-net should be one of:
  LUT z   — SD=1 (enum absent): FF paired with its slice LUT (DI path)
  FF q    — direct FF-to-FF chain via fabric routing (M path)
  routed  — any other real fabric net on the M path (pad inputs, EBR
            reads, wide-mux outputs, ...)
  const   — genuinely tied off (should be RARE)

A high const count means D-input recovery is broken.  Before the SD
polarity fix (2026-07-14) V07 showed 1081/1090 const — the SD enum was
read with inverted polarity and wrong default, so no FF ever resolved
its M wire and DI never resolves via config arcs at all.

Usage: ffd_stats.py [CONFIG]   (default: the V07 bitstream)
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault(
    "TRELLIS_BUILD",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build")
os.environ.setdefault(
    "TRELLIS_DBROOT",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database")

from lifters.machxo2_lift import MachXO2Lift  # noqa: E402

DEFAULT_CONFIG = "/mnt/2tb/git/awto-2000/fpga/v7/FPGA_V07.bin.config"


def main():
    cfg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    device = os.environ.get("TRELLIS_DEVICE", "LCMXO2-1200")

    lift = MachXO2Lift(device)
    pc = lift.parse_config(cfg)
    d = lift.recover_netlist(pc)

    lut_z = {lt["z"] for lt in d.luts if lt["z"]}
    ff_q = {ff["q"] for ff in d.ffs}

    const = lutfed = fffed = routed = 0
    for ff in d.ffs:
        dn = ff["d"]
        if dn.startswith("1'b"):
            const += 1
        elif dn in lut_z:
            lutfed += 1
        elif dn in ff_q:
            fffed += 1
        else:
            routed += 1

    sd0 = sum(1 for en in pc.slice_enum.values()
              for j in (0, 1) if en.get(f"REG{j}.SD") == "0")

    print(f"config      : {cfg}")
    print(f"FFs total   : {len(d.ffs)}")
    print(f"  d = LUT z : {lutfed}   (SD=1, DI path)")
    print(f"  d = FF q  : {fffed}   (M path, FF chain)")
    print(f"  d = routed: {routed}   (M path, other fabric net)")
    print(f"  d = const : {const}   (no driver recovered)")
    print(f"explicit REG.SD 0 enums in config: {sd0}")

    if const > len(d.ffs) // 10:
        print(f"WARNING: {const}/{len(d.ffs)} FFs have constant D — "
              "D-input recovery looks broken", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
