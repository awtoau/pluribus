#!/usr/bin/env python3
"""Pluribus — Stage: signal chain report.

Generates V07-chains.txt from the reachability DB — no hand-coded BFS.
Every section queries reachability / reachability_rev / net_fanout so
results are generic across all pads and all hard IP (EBR, EFB, PLL).

Replaces fpga/scripts/fpga_chain.py (issue #127).

Sections:
  1.  All configured pads — immediate fabric driver (FF / LUT / IOLOGIC / none)
  2.  Hard IP reachability summary (EBR / EFB ports)
  3.  Input pad → EBR write reachability (forward, filter by pad_map src)
  4.  EBR read → output pad reachability (forward, filter by pad_map dst)
  5.  Output pad ← EBR write reverse reachability
  6.  SPI CS (CSSPIN) forward fanout
  7.  Clock domain summary per hard IP tile
"""

import argparse
import sys
from collections import defaultdict
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
    ap.add_argument("--out",       required=True)
    args = ap.parse_args()

    conn = connect()
    cur  = conn.cursor()

    cur.execute("SELECT id FROM bitstreams WHERE label=%s", (args.bitstream,))
    row = cur.fetchone()
    if not row:
        die(f"Bitstream {args.bitstream!r} not found")
    bs_id = row[0]

    lines = []
    L = lines.append

    L(f"== Signal chain report  ({args.bitstream}) ==")
    L(f"source: Pluribus DB — all sections from reachability / net_fanout")
    L("")

    # ── 1. All pads — immediate driver ───────────────────────────────────
    L("-- 1. Pad immediate drivers (all configured pads) --")
    L(f"  {'pin':<4} {'label':<16} {'dir':<6} {'net':<8} {'driver'}")
    L(f"  {'-'*4} {'-'*16} {'-'*6} {'-'*8} {'-'*40}")

    cur.execute("""
        SELECT pm.pin, pm.label, pm.direction, pm.net_in, pm.net_out,
               pm.chip_ref, pm.chip_signal
        FROM pad_map pm
        WHERE pm.bitstream=%s
        ORDER BY pm.pin
    """, (bs_id,))
    pads = cur.fetchall()

    for pin, label, direction, net_in, net_out, chip_ref, chip_signal in pads:
        net = net_out or net_in
        if not net:
            L(f"  {pin:<4} {(label or '?'):<16} {direction:<6} {'(none)':<8} —")
            continue

        # Look up immediate driver from net_fanout (what has out_net = this net).
        # Prefer PAD/FF drivers over synthetic EBR JQ_ff entries; exclude
        # JQ_src (write-transparency) since those are not direct drivers.
        cur.execute("""
            SELECT DISTINCT cell_type, cell, pin AS ipin, net
            FROM net_fanout
            WHERE bitstream=%s AND out_net=%s
              AND pin NOT IN ('JQ_src','JQ_ff')
            LIMIT 3
        """, (bs_id, net))
        drivers = cur.fetchall()
        if not drivers:
            # Fall back to JQ_ff drivers (EBR read output path)
            cur.execute("""
                SELECT DISTINCT cell_type, cell, pin AS ipin, net
                FROM net_fanout
                WHERE bitstream=%s AND out_net=%s AND pin='JQ_ff'
                LIMIT 3
            """, (bs_id, net))
            drivers = cur.fetchall()

        if not drivers:
            # Input pad — check what this net fans out into
            cur.execute("""
                SELECT cell_type, cell, pin AS ipin, out_net
                FROM net_fanout
                WHERE bitstream=%s AND net=%s
                LIMIT 1
            """, (bs_id, net))
            fwd = cur.fetchone()
            driver_str = f"→ {fwd[0]}:{fwd[1]}" if fwd else "(no fanout in netlist)"
        else:
            seen_cells: set = set()
            parts = []
            for ctype, cell, ipin, drv_net in drivers:
                key = (ctype, cell)
                if key in seen_cells:
                    continue
                seen_cells.add(key)
                if ctype == "PAD":
                    parts.append("IOLOGIC")
                elif ctype == "FF":
                    # Get FF D to show if stuck
                    cur.execute("SELECT d, clk FROM ffs WHERE bitstream=%s AND cell=%s",
                                (bs_id, cell))
                    ff = cur.fetchone()
                    d_str = f" D={ff[0]}" if ff else ""
                    clk_str = f" CLK={ff[1]}" if ff else ""
                    parts.append(f"FF:{cell}{d_str}{clk_str}")
                elif ctype == "LUT":
                    parts.append(f"LUT:{cell}")
                else:
                    parts.append(f"{ctype}:{cell}")
            driver_str = "  |  ".join(parts)

        chip_str = f"{chip_ref}/{chip_signal}" if chip_ref else ""
        L(f"  {pin:<4} {(label or '?'):<16} {direction:<6} {net:<8} "
          f"{driver_str:<50} {chip_str}")
    L("")

    # ── 2. Hard IP reachability summary ──────────────────────────────────
    L("-- 2. Hard IP ports (EBR + EFB) --")

    cur.execute("""
        SELECT block, role, count(*) AS n, count(net) AS with_net
        FROM ebr_ports WHERE bitstream=%s
        GROUP BY block, role ORDER BY block, role
    """, (bs_id,))
    ebr_summary = cur.fetchall()

    cur.execute("""
        SELECT block, bus_role, count(*) AS n
        FROM ebr_buses WHERE bitstream=%s
        GROUP BY block, bus_role ORDER BY block, bus_role
    """, (bs_id,))
    bus_rows = cur.fetchall()
    bus_by_block = defaultdict(dict)
    for block, bus_role, n in bus_rows:
        bus_by_block[block][bus_role] = n

    cur_block = None
    for block, role, n, with_net in ebr_summary:
        if block != cur_block:
            buses = bus_by_block.get(block, {})
            bus_str = "  ".join(f"{k}={v}" for k, v in sorted(buses.items()))
            L(f"  {block}  [{bus_str}]")
            cur_block = block
        L(f"    {role:<6} ports={n}  with_net={with_net}")
    L("")

    cur.execute("""
        SELECT port_name, net FROM efb_ports WHERE bitstream=%s ORDER BY port_name
    """, (bs_id,))
    efb = cur.fetchall()
    L(f"  EFB: {len(efb)} ports")
    for port, net in efb[:8]:
        L(f"    {port:<20} net={net}")
    if len(efb) > 8:
        L(f"    ... and {len(efb)-8} more")
    L("")

    # ── 3. Input pad → EBR write reachability ────────────────────────────
    L("-- 3. Input pads → EBR write ports (forward reachability) --")
    L("  Shows which input pads can reach each EBR write net within the BFS depth.")

    cur.execute("""
        SELECT net FROM ebr_ports WHERE bitstream=%s AND role='write' AND net IS NOT NULL
    """, (bs_id,))
    ebr_write_nets = {r[0] for r in cur.fetchall()}

    cur.execute("""
        SELECT pm.pin, pm.label, pm.net_in
        FROM pad_map pm
        WHERE pm.bitstream=%s AND pm.direction='in' AND pm.net_in IS NOT NULL
        ORDER BY pm.pin
    """, (bs_id,))
    input_pads = cur.fetchall()

    # For each input pad, find which EBR write nets it reaches
    pad_to_ebr = defaultdict(list)
    if ebr_write_nets and input_pads:
        in_nets = tuple(p[2] for p in input_pads)
        # Query reachability in bulk: src=pad_net, dst in ebr_write_nets
        cur.execute("""
            SELECT r.src, r.dst, r.min_hops
            FROM reachability r
            WHERE r.bitstream=%s
              AND r.dst = ANY(%s)
              AND r.src = ANY(%s)
            ORDER BY r.src, r.min_hops
        """, (bs_id, list(ebr_write_nets), list(in_nets)))
        for src, dst, hops in cur.fetchall():
            pad_to_ebr[src].append((dst, hops))

    # Group by EBR block
    ebr_net_to_block = {}
    cur.execute("""
        SELECT net, block FROM ebr_ports
        WHERE bitstream=%s AND role='write' AND net IS NOT NULL
    """, (bs_id,))
    for net, block in cur.fetchall():
        ebr_net_to_block[net] = block

    # Build: block → {pad_label: min_hops}
    block_to_pads = defaultdict(dict)
    net_to_pad = {p[2]: (p[0], p[1]) for p in input_pads}
    for pad_net, ebr_hits in pad_to_ebr.items():
        pin, label = net_to_pad.get(pad_net, ('?', pad_net))
        for ebr_net, hops in ebr_hits:
            block = ebr_net_to_block.get(ebr_net, '?')
            existing = block_to_pads[block].get(label, 999)
            if hops < existing:
                block_to_pads[block][label] = hops

    if block_to_pads:
        for block in sorted(block_to_pads):
            pads_str = "  ".join(
                f"{lbl}({h})" for lbl, h in
                sorted(block_to_pads[block].items(), key=lambda x: x[1])
            )
            L(f"  {block}  ←  {pads_str}")
    else:
        L("  (no input pad → EBR write paths found in reachability table)")
    L("")

    # ── 4. EBR read → output pad reachability ────────────────────────────
    L("-- 4. EBR read ports → output pads (forward reachability) --")

    # Source nets = JQ output nets (actual EBR DOB read-data).  These are the
    # out_net values from net_fanout JQ_src rows (write net → JQ net).
    # Also include ebr_ports role='read' nets for EBRs that lack JQ stitching.
    cur.execute("""
        SELECT DISTINCT out_net AS net, cell AS block
        FROM net_fanout
        WHERE bitstream=%s AND pin='JQ_src' AND out_net IS NOT NULL
    """, (bs_id,))
    jq_rows = cur.fetchall()
    jq_nets = [r[0] for r in jq_rows]
    jq_net_to_block = {r[0]: r[1] for r in jq_rows}

    cur.execute("""
        SELECT net, block FROM ebr_ports
        WHERE bitstream=%s AND role='read' AND net IS NOT NULL
    """, (bs_id,))
    ebr_read_rows = cur.fetchall()
    ebr_read_block = {r[0]: r[1] for r in ebr_read_rows}
    # Prefer JQ nets; fall back to ebr_ports 'read' nets for EBRs without JQ
    jq_blocks = {r[1] for r in jq_rows}
    extra_read_nets = [r[0] for r in ebr_read_rows if r[1] not in jq_blocks]
    for r in ebr_read_rows:
        if r[1] not in jq_blocks:
            ebr_read_block[r[0]] = r[1]

    ebr_read_nets = jq_nets + extra_read_nets
    ebr_read_block_merged = {**ebr_read_block, **jq_net_to_block}

    cur.execute("""
        SELECT pm.pin, pm.label, pm.net_out
        FROM pad_map pm
        WHERE pm.bitstream=%s AND pm.direction IN ('out','bidir')
          AND pm.net_out IS NOT NULL
        ORDER BY pm.pin
    """, (bs_id,))
    output_pads = cur.fetchall()
    out_nets = [p[2] for p in output_pads]
    out_net_to_pad = {p[2]: (p[0], p[1]) for p in output_pads}

    ebr_to_pads = defaultdict(list)
    if ebr_read_nets and out_nets:
        cur.execute("""
            SELECT r.src, r.dst, r.min_hops
            FROM reachability r
            WHERE r.bitstream=%s
              AND r.src = ANY(%s)
              AND r.dst = ANY(%s)
            ORDER BY r.src, r.min_hops
        """, (bs_id, ebr_read_nets, out_nets))
        for src, dst, hops in cur.fetchall():
            block = ebr_read_block_merged.get(src, '?')
            pin, label = out_net_to_pad.get(dst, ('?', dst))
            ebr_to_pads[block].append((label, pin, hops))

    if ebr_to_pads:
        for block in sorted(ebr_to_pads):
            # Deduplicate: keep best (min) hops per pad label
            best: dict = {}
            for lbl, pin, h in ebr_to_pads[block]:
                if lbl not in best or h < best[lbl]:
                    best[lbl] = h
            pads_str = "  ".join(
                f"{lbl}({h})" for lbl, h in
                sorted(best.items(), key=lambda x: x[1])
            )
            L(f"  {block}  →  {pads_str}")
    else:
        L("  (no EBR read → output pad paths found in reachability table)")
    L("")

    # ── 5. Output pads ← EBR write (reverse) ─────────────────────────────
    L("-- 5. Output pads ← upstream input pads (reverse reachability) --")
    L("  For each output pad: which input pad nets can reach it?")

    if out_nets:
        # Join to pad_map to restrict src to input pad nets only
        cur.execute("""
            SELECT r.dst, r.src, r.min_hops,
                   nn.name AS src_name
            FROM reachability_rev r
            JOIN pad_map pm ON pm.bitstream=r.bitstream AND pm.net_in=r.src
            LEFT JOIN net_names nn ON nn.bitstream=r.bitstream AND nn.net=r.src
            WHERE r.bitstream=%s
              AND r.dst = ANY(%s)
            ORDER BY r.dst, r.min_hops
        """, (bs_id, out_nets))
        rev_rows = cur.fetchall()
        rev_by_dst = defaultdict(list)
        for dst, src, hops, src_name in rev_rows:
            rev_by_dst[dst].append((src, hops, src_name))

        for pin, label, net_out in output_pads:
            srcs = rev_by_dst.get(net_out, [])
            if not srcs:
                L(f"  pin {pin:<3} {(label or '?'):<16} net={net_out}  ← (no upstream source found)")
            else:
                src_str = "  ".join(
                    f"{sn or src}({h})" for src, h, sn in srcs[:6]
                )
                if len(srcs) > 6:
                    src_str += f"  +{len(srcs)-6} more"
                L(f"  pin {pin:<3} {(label or '?'):<16} net={net_out}  ← {src_str}")
    L("")

    # ── 6. SPI CS (CSSPIN) forward fanout ────────────────────────────────
    L("-- 6. SPI CS (CSSPIN) forward reachability --")

    cur.execute("""
        SELECT pm.pin, pm.net_in FROM pad_map pm
        WHERE pm.bitstream=%s AND pm.si_function LIKE '%%CSSPIN%%'
    """, (bs_id,))
    cs_rows = cur.fetchall()
    for cs_pin, cs_net in cs_rows:
        L(f"  pin {cs_pin}  net={cs_net}")
        if cs_net:
            # total nets reachable
            cur.execute("""
                SELECT count(*) FROM reachability
                WHERE bitstream=%s AND src=%s
            """, (bs_id, cs_net))
            n_total = cur.fetchone()[0]
            # how many of those are FF data inputs
            cur.execute("""
                SELECT count(*) FROM reachability r
                JOIN ffs f ON f.bitstream=r.bitstream AND (f.d=r.dst OR f.ce=r.dst)
                WHERE r.bitstream=%s AND r.src=%s
            """, (bs_id, cs_net))
            n_ff = cur.fetchone()[0]
            # how many of those are output pad nets
            cur.execute("""
                SELECT count(*) FROM reachability r
                JOIN pad_map pm ON pm.bitstream=r.bitstream AND pm.net_out=r.dst
                WHERE r.bitstream=%s AND r.src=%s
            """, (bs_id, cs_net))
            n_pad = cur.fetchone()[0]
            L(f"  reaches: {n_total} nets total  {n_ff} FF inputs  {n_pad} output pads")
            # Show immediate fanout
            cur.execute("""
                SELECT nf.cell_type, nf.cell, nf.out_net
                FROM net_fanout nf
                WHERE nf.bitstream=%s AND nf.net=%s
                LIMIT 8
            """, (bs_id, cs_net))
            for ctype, cell, out_net in cur.fetchall():
                L(f"    → {ctype}:{cell}  out={out_net}")
    L("")

    # ── 7. EBR write clock domains ────────────────────────────────────────
    L("-- 7. Clock domains driving EBR write ports --")

    cur.execute("""
        SELECT ep.block, f.clk, count(*) AS n
        FROM ebr_ports ep
        JOIN net_fanout nf ON nf.bitstream=ep.bitstream AND nf.out_net=ep.net
        JOIN ffs f ON f.bitstream=ep.bitstream AND f.cell=nf.cell
        WHERE ep.bitstream=%s AND ep.role='write'
        GROUP BY ep.block, f.clk
        ORDER BY ep.block, n DESC
    """, (bs_id,))
    clk_rows = cur.fetchall()
    cur_block = None
    for block, clk, n in clk_rows:
        if block != cur_block:
            L(f"  {block}")
            cur_block = block
        # look up clock net name
        cur.execute("""
            SELECT name FROM net_names WHERE bitstream=%s AND net=%s LIMIT 1
        """, (bs_id, clk))
        clk_name = cur.fetchone()
        clk_str = f"{clk} ({clk_name[0]})" if clk_name else clk
        L(f"    CLK={clk_str}  {n} FFs")
    if not clk_rows:
        L("  (no EBR write clock domain data — EBR fanout not in net_fanout)")
    L("")

    cur.close()
    conn.close()

    report = "\n".join(lines) + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write(report)
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
