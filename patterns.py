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

from db import connect, die


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", required=True)
    args = ap.parse_args()

    conn = connect()
    cur  = conn.cursor()   # read cursor
    ins  = conn.cursor()   # write cursor

    cur.execute("SELECT id FROM bitstreams WHERE label=%s", (args.bitstream,))
    row = cur.fetchone()
    if not row:
        die(f"Bitstream {args.bitstream!r} not found")
    bs_id = row[0]

    cur.execute("DELETE FROM patterns WHERE bitstream=%s", (bs_id,))
    deleted = cur.rowcount

    n = {}   # counts per type

    # ── stuck_pad ──────────────────────────────────────────────────────────
    # Output pad whose net is driven solely by a FF with D=const, CE=1, LSR=0
    cur.execute("""
        SELECT pm.pin, pm.label, pm.net_out, f.cell, f.d, f.clk
        FROM pad_map pm
        JOIN ffs f ON f.bitstream = pm.bitstream AND f.q = pm.net_out
        WHERE pm.bitstream = %s
          AND pm.direction IN ('out','bidir')
          AND f.d IN ('1''b0','1''b1')
          AND f.ce = '1''b1'
          AND f.lsr = '1''b0'
        ORDER BY pm.pin
    """, (bs_id,))
    seen_stuck = set()
    for pin, label, net_out, ff_cell, d_val, clk in cur.fetchall():
        if pin in seen_stuck:
            continue
        seen_stuck.add(pin)
        val = "0" if d_val == "1'b0" else "1"
        cur.execute("""
            INSERT INTO patterns (bitstream, pattern_type, label, detail)
            VALUES (%s, 'stuck_pad', %s, %s)
        """, (bs_id, label or f"pin{pin}",
              json.dumps({"pin": pin, "net": net_out, "ff_cell": ff_cell,
                          "stuck_value": val, "clk_net": clk})))
    n["stuck_pad"] = len(seen_stuck)

    # ── orphan_pad ─────────────────────────────────────────────────────────
    # Output pad whose net_out has fanin=0 in net_stats — no fabric driver found
    cur.execute("""
        SELECT pm.pin, pm.label, pm.net_out, ns.fanout
        FROM pad_map pm
        JOIN net_stats ns ON ns.bitstream = pm.bitstream AND ns.net = pm.net_out
        WHERE pm.bitstream = %s
          AND pm.direction IN ('out','bidir')
          AND ns.fanin = 0
        ORDER BY pm.pin
    """, (bs_id,))
    seen_orphan = set()
    for pin, label, net_out, fanout in cur.fetchall():
        if pin in seen_orphan:
            continue
        seen_orphan.add(pin)
        cur.execute("""
            INSERT INTO patterns (bitstream, pattern_type, label, detail)
            VALUES (%s, 'orphan_pad', %s, %s)
        """, (bs_id, label or f"pin{pin}",
              json.dumps({"pin": pin, "net": net_out, "net_fanout": fanout,
                          "note": "No fabric driver in recovered netlist — "
                                  "spine/global route or genuinely floating"})))
    n["orphan_pad"] = len(seen_orphan)

    # ── shared_net_pad ─────────────────────────────────────────────────────
    # Multiple output pads share the same net_out (bus collision / LVDS pair / error)
    cur.execute("""
        SELECT net_out, array_agg(pin ORDER BY pin) AS pins,
               array_agg(label ORDER BY pin) AS labels
        FROM pad_map
        WHERE bitstream = %s
          AND direction IN ('out','bidir')
          AND net_out IS NOT NULL
        GROUP BY net_out
        HAVING count(*) > 1
        ORDER BY net_out
    """, (bs_id,))
    shared_count = 0
    for net_out, pins, labels in cur.fetchall():
        shared_count += 1
        cur.execute("""
            INSERT INTO patterns (bitstream, pattern_type, label, detail)
            VALUES (%s, 'shared_net_pad', %s, %s)
        """, (bs_id, f"net_{net_out}",
              json.dumps({"net": net_out, "pins": pins, "labels": labels,
                          "note": "Multiple output pads share same fabric net — "
                                  "LVDS pair, bus, or netlist recovery gap"})))
    n["shared_net_pad"] = shared_count

    # ── pclk_lane ──────────────────────────────────────────────────────────
    # Any pad with a PCLK/GCLK silicon function — documents clock lane usage
    cur.execute("""
        SELECT pm.pin, pm.label, pm.si_function, pm.direction,
               pm.net_in, pm.net_out, pm.row, pm.col, pm.pio
        FROM pad_map pm
        WHERE pm.bitstream = %s
          AND pm.si_function IS NOT NULL
          AND (pm.si_function LIKE '%%CLK%%' OR pm.si_function LIKE '%%PLL%%')
        ORDER BY pm.pin
    """, (bs_id,))
    pclk_count = 0
    for pin, label, si_fn, direction, net_in, net_out, row, col, pio in cur.fetchall():
        pclk_count += 1
        net = net_in or net_out
        cur.execute("""
            INSERT INTO patterns (bitstream, pattern_type, label, detail)
            VALUES (%s, 'pclk_lane', %s, %s)
        """, (bs_id, label or f"pin{pin}",
              json.dumps({"pin": pin, "si_function": si_fn, "direction": direction,
                          "net": net, "site": f"R{row}C{col}:PIO{pio}"})))
    n["pclk_lane"] = pclk_count

    # ── const_ff ───────────────────────────────────────────────────────────
    # FFs stuck at a constant (D=const, CE=1, LSR=0) not driving a pad
    # (pad-driving ones already captured as stuck_pad)
    cur.execute("""
        SELECT net_out FROM pad_map WHERE bitstream=%s AND net_out IS NOT NULL
    """, (bs_id,))
    pad_out_nets = {r[0] for r in cur.fetchall()}

    cur.execute("""
        SELECT cell, d, clk, q
        FROM ffs
        WHERE bitstream = %s
          AND d IN ('1''b0','1''b1')
          AND ce = '1''b1'
          AND lsr = '1''b0'
        ORDER BY cell
    """, (bs_id,))
    const_ff_count = 0
    for ff_cell, d_val, clk, q in cur.fetchall():
        if q in pad_out_nets:
            continue   # already a stuck_pad
        val = "0" if d_val == "1'b0" else "1"
        cur.execute("""
            INSERT INTO patterns (bitstream, pattern_type, label, detail)
            VALUES (%s, 'const_ff', %s, %s)
        """, (bs_id, ff_cell,
              json.dumps({"ff_cell": ff_cell, "stuck_value": val,
                          "clk_net": clk, "q_net": q,
                          "note": "FF permanently held at constant — "
                                  "unused register or deliberately tied"})))
        const_ff_count += 1
    n["const_ff"] = const_ff_count

    conn.commit()
    cur.close()
    conn.close()

    total = sum(n.values())
    print(f"  patterns: {total} found  "
          + "  ".join(f"{k}={v}" for k, v in sorted(n.items()) if v))


if __name__ == "__main__":
    main()
