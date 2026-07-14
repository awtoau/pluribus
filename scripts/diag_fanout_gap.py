#!/usr/bin/env python3
"""Diagnose pads with net_in but no net_fanout — i.e. an input pad whose
signal never reaches any logic in the recovered netlist.

For each stranded pad it prints the DSU class of the pad's net (every
canonical routing key merged with it) and resolves each key back to the
bel pin it lands on.  A key that resolves to a SLICE FF's M or a LUT's
A/B/C/D means the signal DOES reach logic and the lifter dropped it; a
class with only routing wires means the routing genuinely dead-ends.

See docs/pad-fanout-gap.md for the two failure modes this distinguishes
and what to do about each.

Usage: diag_fanout_gap.py LABEL CONFIG
Env:   TRELLIS_BUILD / TRELLIS_DBROOT / TRELLIS_DEVICE (as for the lifter)

History: this script found the REG.SD polarity bug (fixed 2026-07-14).
A stranded input pad's DSU class contained a SLICE FF's M pin — the FF's
fabric-routed data input — while recover_netlist() was resolving DI
instead, dropping every M-path net in the design.
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import db          # noqa: E402
import schema      # noqa: E402
from sqlalchemy import select, func  # noqa: E402
from lifters.machxo2_lift import MachXO2Lift  # noqa: E402


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: diag_fanout_gap.py LABEL CONFIG")
    label, config = sys.argv[1], sys.argv[2]
    device = os.environ.get("TRELLIS_DEVICE", "LCMXO2-1200")

    conn = db.engine().connect()
    bs = schema.bitstreams
    nf = schema.net_fanout
    pm = schema.pad_map

    bs_id = conn.execute(
        select(bs.c.id).where(bs.c.label == label)).scalar()
    if bs_id is None:
        sys.exit(f"bitstream label {label!r} not loaded")

    unstitched = conn.execute(
        select(pm.c.pin, pm.c.net_in, pm.c.label, pm.c.direction,
               pm.c.row, pm.c.col, pm.c.pio)
        .where(pm.c.bitstream == bs_id)
        .where(pm.c.direction.in_(["in", "bidir"]))
        .where(pm.c.net_in.isnot(None))
        .where(
            ~select(nf.c.id)
            .where(nf.c.bitstream == pm.c.bitstream)
            .where(nf.c.net == pm.c.net_in)
            .correlate(pm)
            .exists()
        )
        .order_by(pm.c.pin)
    ).fetchall()

    print(f"=== {label}: {len(unstitched)} pads with net_in but no "
          f"net_fanout ===\n")
    for r in unstitched:
        as_output = conn.execute(
            select(func.count())
            .where(nf.c.bitstream == bs_id)
            .where(nf.c.out_net == r.net_in)
        ).scalar()
        print(f"pin={r.pin:3d}  R{r.row}C{r.col}{r.pio or ''}  "
              f"{r.direction:5s}  net={r.net_in:8s}  {r.label}"
              f"   (appears as a fanout OUT_net {as_output}x)")
    if not unstitched:
        return 0
    print()

    # Recover the netlist so we can inspect DSU classes and bel pins.
    lift = MachXO2Lift(device)
    pc = lift.parse_config(config)
    d = lift.recover_netlist(pc)

    # canonical key -> "SLICEB.FF1.M" style name, for every tile we touch
    def bel_pin_names(key):
        col, row, _wid = key
        hits = []
        for bname, pins in lift.bels_of(row, col).items():
            for pname, pkey in pins.items():
                if pkey == key:
                    hits.append(f"{bname}.{pname}")
        return hits

    for r in unstitched:
        net = r.net_in
        root = next((k for k, n in d.net_name.items() if n == net), None)
        if root is None:
            print(f"pin={r.pin} net={net}: NOT FOUND in recovered netlist\n")
            continue
        cls = sorted(k for k in d.dsu.p if d.dsu.find(k) == root)
        print(f"pin={r.pin} {r.label} net={net}: DSU class size={len(cls)}")
        for k in cls:
            names = bel_pin_names(k)
            tag = "  <- " + ", ".join(names) if names else ""
            print(f"    {k}{tag}")

        lut_uses = [(lt["name"], p) for lt in d.luts
                    for p in ("a", "b", "c", "d") if lt.get(p) == net]
        ff_uses = [(ff["name"], p) for ff in d.ffs
                   for p, attr in (("D", "d"), ("CLK", "clk"),
                                   ("CE", "ce"), ("LSR", "lsr"))
                   if ff.get(attr) == net]
        print(f"    consumed by {len(lut_uses)} LUT input(s), "
              f"{len(ff_uses)} FF input(s)")
        for n_, p in (lut_uses + ff_uses)[:6]:
            print(f"      {n_}.{p}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
