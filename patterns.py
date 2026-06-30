#!/usr/bin/env python3
"""Pluribus — Stage: pattern detection.

Detects mechanical structural patterns from the DB and writes them to the
`patterns` table.  Runs after reach3 (const_nets, net_stats must be populated).

Patterns detected:
  stuck_pad       output pad driven by a FF with const D (permanently 0 or 1)
  orphan_pad      output pad whose net has fanin=0 in the recovered netlist
                  (spine-driven, globally-routed, or genuinely floating)
  shared_net_pad  multiple pads share the same net_out (wired-or / bus collision)
  pclk_lane       PCLK-capable pad — documents which clock lanes are in use
  const_ff        FF with D=const and CE=1, LSR=0 (registered constant driver)
"""

import argparse
import json
import sys
from pathlib import Path

_HERE    = Path(__file__).parent
_SCRIPTS = _HERE.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_HERE))

from sqlalchemy import select, insert, delete, func, and_
import schema
from db import engine, die, BACKEND


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", required=True)
    args = ap.parse_args()

    with engine().begin() as conn:
        # ── resolve bitstream id ───────────────────────────────────────────
        row = conn.execute(
            select(schema.bitstreams.c.id).where(
                schema.bitstreams.c.label == args.bitstream
            )
        ).fetchone()
        if not row:
            die(f"Bitstream {args.bitstream!r} not found")
        bs_id = row[0]

        conn.execute(
            delete(schema.patterns).where(schema.patterns.c.bitstream == bs_id)
        )

        n = {}   # counts per type

        # ── stuck_pad ──────────────────────────────────────────────────────
        # Output pad whose net is driven solely by a FF with D=const, CE=1, LSR=0
        pm  = schema.pad_map
        ffs = schema.ffs
        stuck_rows = conn.execute(
            select(
                pm.c.pin, pm.c.label, pm.c.net_out,
                ffs.c.cell, ffs.c.d, ffs.c.clk,
            )
            .join(ffs, and_(
                ffs.c.bitstream == pm.c.bitstream,
                ffs.c.q         == pm.c.net_out,
            ))
            .where(
                pm.c.bitstream == bs_id,
                pm.c.direction.in_(["out", "bidir"]),
                ffs.c.d.in_(["1'b0", "1'b1"]),
                ffs.c.ce  == "1'b1",
                ffs.c.lsr == "1'b0",
            )
            .order_by(pm.c.pin)
        ).fetchall()

        seen_stuck = set()
        stuck_inserts = []
        for pin, label, net_out, ff_cell, d_val, clk in stuck_rows:
            if pin in seen_stuck:
                continue
            seen_stuck.add(pin)
            val = "0" if d_val == "1'b0" else "1"
            stuck_inserts.append({
                "bitstream":    bs_id,
                "pattern_type": "stuck_pad",
                "label":        label or f"pin{pin}",
                "detail":       json.dumps({"pin": pin, "net": net_out,
                                            "ff_cell": ff_cell,
                                            "stuck_value": val, "clk_net": clk}),
            })
        if stuck_inserts:
            conn.execute(insert(schema.patterns), stuck_inserts)
        n["stuck_pad"] = len(seen_stuck)

        # ── orphan_pad ─────────────────────────────────────────────────────
        # Output pad whose net_out has fanin=0 in net_stats — no fabric driver found
        ns = schema.net_stats
        orphan_rows = conn.execute(
            select(pm.c.pin, pm.c.label, pm.c.net_out, ns.c.fanout)
            .join(ns, and_(
                ns.c.bitstream == pm.c.bitstream,
                ns.c.net       == pm.c.net_out,
            ))
            .where(
                pm.c.bitstream == bs_id,
                pm.c.direction.in_(["out", "bidir"]),
                ns.c.fanin == 0,
            )
            .order_by(pm.c.pin)
        ).fetchall()

        seen_orphan = set()
        orphan_inserts = []
        for pin, label, net_out, fanout in orphan_rows:
            if pin in seen_orphan:
                continue
            seen_orphan.add(pin)
            orphan_inserts.append({
                "bitstream":    bs_id,
                "pattern_type": "orphan_pad",
                "label":        label or f"pin{pin}",
                "detail":       json.dumps({"pin": pin, "net": net_out,
                                            "net_fanout": fanout,
                                            "note": "No fabric driver in recovered netlist — "
                                                    "spine/global route or genuinely floating"}),
            })
        if orphan_inserts:
            conn.execute(insert(schema.patterns), orphan_inserts)
        n["orphan_pad"] = len(seen_orphan)

        # ── shared_net_pad ─────────────────────────────────────────────────
        # Multiple output pads share the same net_out (bus collision / LVDS pair / error)
        if BACKEND == "sqlite":
            agg_pins   = func.json_group_array(pm.c.pin)
            agg_labels = func.json_group_array(pm.c.label)
        else:
            agg_pins   = func.array_agg(pm.c.pin)
            agg_labels = func.array_agg(pm.c.label)

        shared_rows = conn.execute(
            select(
                pm.c.net_out,
                agg_pins.label("pins"),
                agg_labels.label("labels"),
            )
            .where(
                pm.c.bitstream == bs_id,
                pm.c.direction.in_(["out", "bidir"]),
                pm.c.net_out.isnot(None),
            )
            .group_by(pm.c.net_out)
            .having(func.count() > 1)
            .order_by(pm.c.net_out)
        ).fetchall()

        shared_inserts = []
        for net_out, pins, labels in shared_rows:
            # SQLite returns JSON strings; Postgres returns Python lists
            pins_list   = json.loads(pins)   if isinstance(pins,   str) else list(pins)
            labels_list = json.loads(labels) if isinstance(labels, str) else list(labels)
            shared_inserts.append({
                "bitstream":    bs_id,
                "pattern_type": "shared_net_pad",
                "label":        f"net_{net_out}",
                "detail":       json.dumps({"net": net_out,
                                            "pins": pins_list, "labels": labels_list,
                                            "note": "Multiple output pads share same fabric net — "
                                                    "LVDS pair, bus, or netlist recovery gap"}),
            })
        if shared_inserts:
            conn.execute(insert(schema.patterns), shared_inserts)
        n["shared_net_pad"] = len(shared_inserts)

        # ── pclk_lane ──────────────────────────────────────────────────────
        # Any pad with a PCLK/GCLK silicon function — documents clock lane usage
        pclk_rows = conn.execute(
            select(
                pm.c.pin, pm.c.label, pm.c.si_function, pm.c.direction,
                pm.c.net_in, pm.c.net_out, pm.c.row, pm.c.col, pm.c.pio,
            )
            .where(
                pm.c.bitstream == bs_id,
                pm.c.si_function.isnot(None),
                func.upper(pm.c.si_function).like("%CLK%")
                | func.upper(pm.c.si_function).like("%PLL%"),
            )
            .order_by(pm.c.pin)
        ).fetchall()

        pclk_inserts = []
        for pin, label, si_fn, direction, net_in, net_out, row, col, pio in pclk_rows:
            net = net_in or net_out
            pclk_inserts.append({
                "bitstream":    bs_id,
                "pattern_type": "pclk_lane",
                "label":        label or f"pin{pin}",
                "detail":       json.dumps({"pin": pin, "si_function": si_fn,
                                            "direction": direction, "net": net,
                                            "site": f"R{row}C{col}:PIO{pio}"}),
            })
        if pclk_inserts:
            conn.execute(insert(schema.patterns), pclk_inserts)
        n["pclk_lane"] = len(pclk_inserts)

        # ── const_ff ───────────────────────────────────────────────────────
        # FFs stuck at a constant (D=const, CE=1, LSR=0) not driving a pad
        # (pad-driving ones already captured as stuck_pad)
        pad_out_nets = {
            r[0] for r in conn.execute(
                select(pm.c.net_out)
                .where(
                    pm.c.bitstream == bs_id,
                    pm.c.net_out.isnot(None),
                )
            ).fetchall()
        }

        ff_rows = conn.execute(
            select(ffs.c.cell, ffs.c.d, ffs.c.clk, ffs.c.q)
            .where(
                ffs.c.bitstream == bs_id,
                ffs.c.d.in_(["1'b0", "1'b1"]),
                ffs.c.ce  == "1'b1",
                ffs.c.lsr == "1'b0",
            )
            .order_by(ffs.c.cell)
        ).fetchall()

        cff_inserts = []
        for ff_cell, d_val, clk, q in ff_rows:
            if q in pad_out_nets:
                continue   # already a stuck_pad
            val = "0" if d_val == "1'b0" else "1"
            cff_inserts.append({
                "bitstream":    bs_id,
                "pattern_type": "const_ff",
                "label":        ff_cell,
                "detail":       json.dumps({"ff_cell": ff_cell, "stuck_value": val,
                                            "clk_net": clk, "q_net": q,
                                            "note": "FF permanently held at constant — "
                                                    "unused register or deliberately tied"}),
            })
        if cff_inserts:
            conn.execute(insert(schema.patterns), cff_inserts)
        n["const_ff"] = len(cff_inserts)

    total = sum(n.values())
    print(f"  patterns: {total} found  "
          + "  ".join(f"{k}={v}" for k, v in sorted(n.items()) if v))


if __name__ == "__main__":
    main()
