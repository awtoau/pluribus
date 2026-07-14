#!/usr/bin/env python3
"""Cross-bitstream pad comparison: for every pin in pad_map, show per
bitstream the direction and whether its input net is stitched into logic
(has net_fanout rows).  Corroborates the board pinout: if independent
firmware versions all configure a pin the same way and route it to
fabric, the pin annotation is confirmed.

Usage: compare_pads.py [LABEL ...]   (default: all loaded bitstreams)
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db, schema
from sqlalchemy import select


def main():
    conn = db.engine().connect()
    bs = schema.bitstreams
    pm = schema.pad_map
    nf = schema.net_fanout

    want = sys.argv[1:]
    rows = conn.execute(select(bs.c.id, bs.c.label).order_by(bs.c.id)).fetchall()
    labels = {r.id: r.label for r in rows
              if not want or r.label in want}
    if not labels:
        sys.exit(f"no bitstreams matching {want}; loaded: "
                 f"{[r.label for r in rows]}")

    # nets with at least one fanout row, per bitstream
    stitched = {}
    for bid in labels:
        nets = {r.net for r in conn.execute(
            select(nf.c.net).where(nf.c.bitstream == bid).distinct()
        )}
        stitched[bid] = nets

    # pad rows keyed by pin
    pads = {}   # pin -> {bid: row}
    label_of_pin = {}
    for bid in labels:
        for r in conn.execute(
            select(pm.c.pin, pm.c.label, pm.c.direction, pm.c.net_in,
                   pm.c.net_out, pm.c.row, pm.c.col, pm.c.pio)
            .where(pm.c.bitstream == bid)
        ):
            pads.setdefault(r.pin, {})[bid] = r
            label_of_pin[r.pin] = r.label

    bids = sorted(labels)
    hdr_labels = [labels[b] for b in bids]
    print(f"{'pin':>4} {'signal':<12} {'site':<12}", end="")
    for hl in hdr_labels:
        print(f" | {hl:<14}", end="")
    print()
    print("-" * (32 + 17 * len(bids)))

    agree_dir = disagree = 0
    for pin in sorted(pads):
        per = pads[pin]
        any_row = next(iter(per.values()))
        site = f"R{any_row.row}C{any_row.col}{any_row.pio or ''}"
        print(f"{pin:>4} {label_of_pin[pin]:<12} {site:<12}", end="")
        dirs = set()
        for b in bids:
            r = per.get(b)
            if r is None:
                print(f" | {'--absent--':<14}", end="")
                continue
            dirs.add(r.direction)
            mark = ""
            if r.direction in ("in", "bidir") and r.net_in:
                mark = "+fan" if r.net_in in stitched[b] else "NOFAN"
            cell = f"{r.direction}:{mark}" if mark else r.direction
            print(f" | {cell:<14}", end="")
        print()
        if len(dirs) == 1:
            agree_dir += 1
        else:
            disagree += 1

    print(f"\npins with identical direction across bitstreams: {agree_dir}")
    print(f"pins with differing direction: {disagree}")
    print("\nkey: +fan = input net drives logic (net_fanout present); "
          "NOFAN = input net stranded (modelling gap)")


if __name__ == "__main__":
    main()
