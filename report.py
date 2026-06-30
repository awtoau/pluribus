#!/usr/bin/env python3
"""Pluribus — human-readable RE status report.

Queries the DB and prints a complete, self-contained status report of
everything known about the current bitstream.  One command, full situational
awareness.  No manual SQL needed.

Usage
-----
  python3 fpga/pluribus/report.py [--bitstream V07] [--out report.txt]
"""

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import connect, die


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AEST = timezone(timedelta(hours=10))


def net_label(net, net_names):
    """Return the human name for a net, or '(unnamed)' if not annotated."""
    return net_names.get(net, "(unnamed)")


def net_with_name(net, net_names):
    """Return 'net(NAME)' or just 'net' when unnamed — avoids double parens."""
    name = net_names.get(net)
    if name:
        return f"{net}({name})"
    return net


def net_display(net, net_names):
    """Return 'net  NAME' or 'net  (unnamed)' — suitable for table columns."""
    name = net_names.get(net)
    if name:
        return f"{net}  {name}"
    return f"{net}  (unnamed)"


def hops_str(n_hops):
    """Return 'N hop' or 'N hops' with correct pluralisation."""
    return f"{n_hops} hop" if n_hops == 1 else f"{n_hops} hops"


def _fetch_net_names(cur, bs_id):
    """Return {net: name} dict for all named nets in this bitstream."""
    cur.execute(
        "SELECT net, name FROM net_names WHERE bitstream=%s",
        (bs_id,),
    )
    return dict(cur.fetchall())


# ---------------------------------------------------------------------------
# Section 1: Header
# ---------------------------------------------------------------------------

def section_header(cur, bs_id):
    """Print the report header with bitstream metadata and generation timestamp."""
    cur.execute(
        "SELECT label, device, package, loaded_at FROM bitstreams WHERE id=%s",
        (bs_id,),
    )
    label, device, package, loaded_at = cur.fetchone()

    now = datetime.now(AEST).strftime("%Y-%m-%dT%H:%M:%S+10:00")

    lines = [
        "═══════════════════════════════════════════════════════",
        f" Pluribus RE Report — {label}  ({device} {package})",
        f" Generated: {now}",
        f" Bitstream loaded: {loaded_at.astimezone(AEST).strftime('%Y-%m-%dT%H:%M:%S+10:00')}",
        "═══════════════════════════════════════════════════════",
    ]
    return lines


# ---------------------------------------------------------------------------
# Section 2: Netlist Summary
# ---------------------------------------------------------------------------

def section_netlist(cur, bs_id):
    """Summarise the raw netlist: FF/LUT/net counts, naming coverage, clocks."""
    cur.execute("SELECT count(*) FROM ffs WHERE bitstream=%s", (bs_id,))
    n_ffs = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM luts WHERE bitstream=%s", (bs_id,))
    n_luts = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM nets WHERE bitstream=%s", (bs_id,))
    n_nets = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM net_fanout WHERE bitstream=%s", (bs_id,))
    n_fanout = cur.fetchone()[0]

    # Average and max fanout per net (from net_stats)
    cur.execute(
        "SELECT avg(fanout), max(fanout) FROM net_stats WHERE bitstream=%s",
        (bs_id,),
    )
    row = cur.fetchone()
    avg_fo = float(row[0]) if row[0] is not None else 0.0
    max_fo = row[1] or 0

    # Named nets
    cur.execute("SELECT count(*) FROM net_names WHERE bitstream=%s", (bs_id,))
    n_named_nets = cur.fetchone()[0]
    pct_nets = 100.0 * n_named_nets / n_nets if n_nets else 0.0

    # Named cells
    cur.execute("SELECT count(*) FROM cell_names WHERE bitstream=%s", (bs_id,))
    n_named_cells = cur.fetchone()[0]
    n_cells = n_ffs + n_luts
    pct_cells = 100.0 * n_named_cells / n_cells if n_cells else 0.0

    # Clock domains — distinct clock nets
    cur.execute(
        "SELECT count(DISTINCT clk_net) FROM clock_domains WHERE bitstream=%s",
        (bs_id,),
    )
    n_clk_domains = cur.fetchone()[0]

    # Active FFs (D != 1'b0)
    cur.execute(
        "SELECT count(*) FROM ffs WHERE bitstream=%s AND d != '1''b0'",
        (bs_id,),
    )
    n_active_ffs = cur.fetchone()[0]
    n_stuck_ffs = n_ffs - n_active_ffs

    # Const nets
    cur.execute("SELECT count(*) FROM const_nets WHERE bitstream=%s", (bs_id,))
    n_const_nets = cur.fetchone()[0]

    lines = [
        "",
        "── Netlist ─────────────────────────────────────────────",
        f"  FFs:            {n_ffs:>5}   ({n_stuck_ffs} stuck-at-reset, {n_active_ffs} active)",
        f"  LUTs:           {n_luts:>5}",
        f"  Nets:           {n_nets:>5}",
        f"  Fanout edges:   {n_fanout:>5}   (avg {avg_fo:.1f} per net, max {max_fo})",
        f"  Named nets:     {n_named_nets:>5} / {n_nets}  ({pct_nets:.1f}%)",
        f"  Named cells:    {n_named_cells:>5} / {n_cells}  ({pct_cells:.1f}%)",
        f"  Clock domains:  {n_clk_domains:>5}   ({n_clk_domains} ghost clock nets — hard IP spine)",
        f"  Const nets:     {n_const_nets:>5}   (propagated from CONST0/CONST1 LUTs + stuck FFs)",
    ]
    return lines


# ---------------------------------------------------------------------------
# Section 3: Clock Architecture
# ---------------------------------------------------------------------------

def section_clocks(cur, bs_id, net_names):
    """List clock domains ranked by FF count with crossing counts."""
    cur.execute(
        """
        SELECT cd.clk_net, count(*) AS n_ffs
        FROM clock_domains cd
        WHERE cd.bitstream=%s
        GROUP BY cd.clk_net ORDER BY n_ffs DESC
        """,
        (bs_id,),
    )
    domains = cur.fetchall()

    # Crossings-in and crossings-out per clock net
    cur.execute(
        "SELECT dst_clk, count(*) FROM clock_crossings WHERE bitstream=%s GROUP BY dst_clk",
        (bs_id,),
    )
    crossings_in = dict(cur.fetchall())

    cur.execute(
        "SELECT src_clk, count(*) FROM clock_crossings WHERE bitstream=%s GROUP BY src_clk",
        (bs_id,),
    )
    crossings_out = dict(cur.fetchall())

    n_total = len(domains)

    lines = [
        "",
        "── Clock Architecture ──────────────────────────────────",
        f"  {'Rank':<5}  {'Net':<8}  {'Name':<20}  {'FFs':>5}  {'Cross-in':>9}  {'Cross-out':>9}",
    ]
    for rank, (clk_net, n_ffs) in enumerate(domains):
        name = net_names.get(clk_net, "(unnamed)")
        ci = crossings_in.get(clk_net, 0)
        co = crossings_out.get(clk_net, 0)
        lines.append(
            f"  {rank:<5}  {clk_net:<8}  {name:<20}  {n_ffs:>5}  {ci:>9}  {co:>9}"
        )
    lines.append(f"  ({n_total} total clock domains)")
    return lines


# ---------------------------------------------------------------------------
# Section 4: Physical Boundary
# ---------------------------------------------------------------------------

def section_boundary(cur, bs_id, net_names):
    """Summarise the physical pad map and EFB ports."""
    cur.execute("SELECT count(*) FROM pad_map WHERE bitstream=%s", (bs_id,))
    n_total_pads = cur.fetchone()[0]

    cur.execute(
        "SELECT count(*) FROM pad_map WHERE bitstream=%s AND (net_in IS NOT NULL OR net_out IS NOT NULL)",
        (bs_id,),
    )
    n_resolved = cur.fetchone()[0]
    n_unresolved = n_total_pads - n_resolved

    # Input pads
    cur.execute(
        "SELECT pin, label, net_in FROM pad_map WHERE bitstream=%s AND net_in IS NOT NULL ORDER BY pin",
        (bs_id,),
    )
    input_pads = cur.fetchall()

    # Output pads
    cur.execute(
        "SELECT pin, label, net_out FROM pad_map WHERE bitstream=%s AND net_out IS NOT NULL ORDER BY pin",
        (bs_id,),
    )
    output_pads = cur.fetchall()

    # EFB ports
    cur.execute(
        "SELECT port_name, net FROM efb_ports WHERE bitstream=%s ORDER BY port_name",
        (bs_id,),
    )
    efb_ports = cur.fetchall()

    lines = [
        "",
        "── Physical Boundary ───────────────────────────────────",
        f"  Pads total:     {n_total_pads}",
        f"  Resolved:       {n_resolved}  (net_in or net_out populated)",
        f"  Unresolved:     {n_unresolved}  (no routing arc in bitstream — pad unused by design)",
        "",
        f"  Inputs ({len(input_pads)} pads with net_in):",
    ]

    for pin, label, net in input_pads:
        # reachability stats
        cur.execute(
            """
            SELECT count(*), min(r.min_hops)
            FROM reachability r
            JOIN ffs f ON f.bitstream=r.bitstream AND (f.d=r.dst OR f.ce=r.dst)
            WHERE r.bitstream=%s AND r.src=%s
            """,
            (bs_id, net),
        )
        r = cur.fetchone()
        n_ffs_reach = r[0] if r else 0
        min_hops = r[1] if r else None

        hop_str = f"{n_ffs_reach} FFs in {hops_str(min_hops)}" if min_hops is not None else "no reach data"
        name = net_names.get(net, label)
        lines.append(f"    {name:<12}  pin{pin:<4}  {net:<8}  → reach: {hop_str}")

    if not input_pads:
        lines.append("    (none)")

    lines.append("")
    lines.append(f"  Outputs ({len(output_pads)} pads with net_out):")

    for pin, label, net in output_pads:
        # Find what drives the net (FF or LUT)
        cur.execute(
            "SELECT cell, clk FROM ffs WHERE bitstream=%s AND q=%s",
            (bs_id, net),
        )
        row = cur.fetchone()
        if row:
            ff_cell, clk = row
            # After pass 7 (pad propagation), the driving FF may be named in cell_names
            cur.execute(
                "SELECT name FROM cell_names WHERE bitstream=%s AND cell=%s",
                (bs_id, ff_cell),
            )
            cn = cur.fetchone()
            ff_label = cn[0] if cn else ff_cell
            driver_str = f"ff={ff_label}  clk={net_with_name(clk, net_names)}"
        else:
            cur.execute(
                "SELECT cell, fn FROM luts WHERE bitstream=%s AND z=%s",
                (bs_id, net),
            )
            row = cur.fetchone()
            if row:
                driver_str = f"lut={row[0]}  fn={row[1]}"
            else:
                driver_str = "unknown driver"
        name = net_names.get(net, label)
        lines.append(f"    {name:<12}  pin{pin:<4}  {net:<8}  ← {driver_str}")

    if not output_pads:
        lines.append("    (none)")

    lines.append("")
    lines.append(f"  EFB ports ({len(efb_ports)}):")

    for port_name, net in efb_ports:
        cur.execute(
            "SELECT count(*) FROM net_fanout WHERE bitstream=%s AND net=%s",
            (bs_id, net),
        )
        fo = cur.fetchone()[0]

        cur.execute(
            """
            SELECT count(*), min(r.min_hops)
            FROM reachability r
            JOIN ffs f ON f.bitstream=r.bitstream AND (f.d=r.dst OR f.ce=r.dst)
            WHERE r.bitstream=%s AND r.src=%s
            """,
            (bs_id, net),
        )
        r = cur.fetchone()
        n_ff_reach = r[0] if r else 0
        min_hops = r[1] if r else None

        hop_str = (
            f"{n_ff_reach} FFs in {hops_str(min_hops)}"
            if min_hops is not None
            else "no reach data"
        )
        dest_str = f"fanout={fo}  reach: {hop_str}"
        lines.append(f"    {port_name:<12}  {net:<8}  {dest_str}")

    if not efb_ports:
        lines.append("    (none)")

    return lines


# ---------------------------------------------------------------------------
# Section 5: Active Logic
# ---------------------------------------------------------------------------

def section_active_ffs(cur, bs_id, net_names):
    """Detail the non-reset FFs — the only FFs doing actual work."""
    cur.execute(
        "SELECT cell, clk, ce, d, q FROM ffs WHERE bitstream=%s AND d != '1''b0' ORDER BY cell",
        (bs_id,),
    )
    active = cur.fetchall()

    lines = [
        "",
        f"── Active Flip-Flops ({len(active)}) ───────────────────────────",
        "  These FFs have real D inputs — the active logic in this design.",
    ]

    for ff_cell, clk, ce, d_net, q_net in active:

        # D-function expression
        cur.execute(
            "SELECT fn_expr FROM ff_d_functions WHERE ff_cell=%s",
            (ff_cell,),
        )
        row = cur.fetchone()
        fn_expr = row[0] if row else d_net

        # Is D net a ghost (fanin=0)?
        cur.execute(
            "SELECT fanin FROM net_stats WHERE bitstream=%s AND net=%s",
            (bs_id, d_net),
        )
        row = cur.fetchone()
        fanin = row[0] if row else None

        if fanin == 0:
            # Show resolved name if pass 7+ gave it something other than auto_ghost
            cur.execute(
                "SELECT name, source FROM net_names WHERE bitstream=%s AND net=%s",
                (bs_id, d_net),
            )
            nn = cur.fetchone()
            if nn and nn[1] != 'auto_ghost':
                d_annotation = f"{d_net}  (ghost net — fanin=0, hard IP source; resolved: {nn[0]})"
            else:
                d_annotation = f"{d_net}  (ghost net — fanin=0, hard IP source)"
        else:
            d_annotation = fn_expr or d_net

        # Pad influence
        cur.execute(
            "SELECT array_agg(pad_label ORDER BY pad_label) FROM pad_ff_influence WHERE bitstream=%s AND ff_cell=%s",
            (bs_id, ff_cell),
        )
        row = cur.fetchone()
        pad_labels = row[0] if row and row[0] else []

        pad_str = ", ".join(pad_labels) if pad_labels else "none"

        # Clock crossings from this FF's Q
        cur.execute(
            "SELECT count(DISTINCT dst_clk) FROM clock_crossings WHERE bitstream=%s AND src_ff=%s",
            (bs_id, ff_cell),
        )
        n_cross = cur.fetchone()[0]

        lines.append("")
        lines.append(
            f"  {ff_cell}    clk={net_with_name(clk, net_names) if clk else 'none'}   D={d_net}  CE={ce}   Q={q_net}"
        )
        lines.append(f"    D-function: {d_annotation}")
        lines.append(f"    Pad influence: {pad_str}")
        lines.append(f"    Clock crossings from Q: {n_cross} other domain(s)")

    if not active:
        lines.append("  (none — all FFs stuck at reset)")

    return lines


# ---------------------------------------------------------------------------
# Section 6: Register Map (spatial clusters)
# ---------------------------------------------------------------------------

def section_register_clusters(cur, bs_id, net_names):
    """Group FFs by tile location to identify register banks."""
    cur.execute(
        """
        SELECT substring(cell, 1, length(cell)-3) AS tile,
               count(*)                 AS n_ffs,
               array_agg(DISTINCT clk) AS clks,
               array_agg(DISTINCT ce)  AS ces
        FROM ffs WHERE bitstream=%s
        GROUP BY tile ORDER BY n_ffs DESC, tile
        """,
        (bs_id,),
    )
    clusters = cur.fetchall()

    cur.execute(
        """
        SELECT count(DISTINCT substring(cell, 1, length(cell)-3))
        FROM ffs WHERE bitstream=%s
        """,
        (bs_id,),
    )
    n_tiles = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM ffs WHERE bitstream=%s", (bs_id,))
    n_total_ffs = cur.fetchone()[0]

    # Mixed-clock tiles
    cur.execute(
        """
        SELECT substring(cell, 1, length(cell)-3) AS tile,
               array_agg(DISTINCT clk) AS clks,
               count(*) AS n_ffs
        FROM ffs WHERE bitstream=%s
        GROUP BY tile HAVING count(DISTINCT clk) > 1
        ORDER BY tile
        """,
        (bs_id,),
    )
    mixed_clock = cur.fetchall()

    lines = [
        "",
        "── Register Clusters ───────────────────────────────────",
        f"  {n_tiles} tile groups, {n_total_ffs} FFs total",
        "",
        "  Largest groups (8 FFs per full tile):",
    ]

    # Show top 20 tiles
    for tile, n_ffs, clks, ces in clusters[:20]:
        clk_str = ", ".join(c for c in clks if c)
        ce_str  = ", ".join(c for c in ces  if c)
        clk_names = ", ".join(
            f"{c}({net_names[c]})" if c in net_names else c
            for c in clks if c
        )
        lines.append(
            f"  {tile:<14}  {n_ffs} FFs   clk={clk_names or clk_str}   ce={ce_str or '1''b1'}"
        )

    if len(clusters) > 20:
        lines.append(f"  ... ({len(clusters) - 20} more tiles not shown)")

    lines.append("")
    lines.append(f"  Mixed-clock tiles ({len(mixed_clock)} — potential CDC inside tile):")
    for tile, clks, n_ffs in mixed_clock[:20]:
        clk_str = ", ".join(c for c in clks if c)
        lines.append(f"    {tile:<14}  {n_ffs} FFs  clks: {clk_str}")

    if len(mixed_clock) > 20:
        lines.append(f"    ... ({len(mixed_clock) - 20} more)")

    if not mixed_clock:
        lines.append("    (none)")

    return lines


# ---------------------------------------------------------------------------
# Section 7: Clock Crossings Summary
# ---------------------------------------------------------------------------

def section_clock_crossings(cur, bs_id, net_names):
    """Summarise potential metastability hazards across clock domains."""
    cur.execute("SELECT count(*) FROM clock_crossings WHERE bitstream=%s", (bs_id,))
    n_total = cur.fetchone()[0]

    # Top crossing pairs
    cur.execute(
        """
        SELECT src_clk, dst_clk, count(*) AS n
        FROM clock_crossings WHERE bitstream=%s
        GROUP BY src_clk, dst_clk ORDER BY n DESC LIMIT 15
        """,
        (bs_id,),
    )
    top_pairs = cur.fetchall()

    # Most dangerous dst FFs (receives from most distinct source domains)
    cur.execute(
        """
        SELECT dst_ff, dst_clk, count(DISTINCT src_clk) AS n_srcs
        FROM clock_crossings WHERE bitstream=%s
        GROUP BY dst_ff, dst_clk ORDER BY n_srcs DESC LIMIT 10
        """,
        (bs_id,),
    )
    dangerous = cur.fetchall()

    lines = [
        "",
        f"── Clock Domain Crossings ({n_total} total) ──────────────────",
        "  Potential metastability hazards — signals crossing clock domains",
        "  without a synchroniser detected in static analysis.",
        "",
        "  Top crossing pairs:",
        f"  {'Source clock':<30}  {'Dest clock':<30}  {'FFs':>6}",
    ]

    for src_clk, dst_clk, n in top_pairs:
        src_label = net_with_name(src_clk, net_names)
        dst_label = net_with_name(dst_clk, net_names)
        lines.append(f"  {src_label:<30}  {dst_label:<30}  {n:>6}")

    if n_total == 0:
        lines.append("  (none)")

    lines.append("")
    lines.append("  Most dangerous dest FFs (receives from most source domains):")
    for dst_ff, dst_clk, n_srcs in dangerous:
        lines.append(
            f"    {dst_ff:<20}  dst_clk={net_with_name(dst_clk, net_names)}  from {n_srcs} domain(s)"
        )

    if not dangerous:
        lines.append("    (none)")

    return lines


# ---------------------------------------------------------------------------
# Section 7b: CDC Synchronisers
# ---------------------------------------------------------------------------

def section_cdc_synchronisers(cur, bs_id, net_names):
    """List detected 2-FF CDC synchroniser chains (named by pass 9 of reach4)."""
    # Guard: table may not exist if reach4 pass 9 hasn't been run yet
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'cdc_synchronisers'
        )
        """
    )
    if not cur.fetchone()[0]:
        return [
            "",
            "── CDC Synchronisers ────────────────────────────────────",
            "  (cdc_synchronisers table not found — run reach4 pass 9)",
        ]

    cur.execute(
        """
        SELECT src_ff, src_clk, stage1_ff, stage2_ff, dst_clk
        FROM cdc_synchronisers WHERE bitstream=%s
        ORDER BY dst_clk, src_clk
        """,
        (bs_id,),
    )
    rows = cur.fetchall()
    n_sync = len(rows)

    lines = [
        "",
        "── CDC Synchronisers ────────────────────────────────────",
        f"  {n_sync} synchroniser pair(s) detected (removed from unverified crossing count)",
        "",
        "  src_ff(src_clk) → stage1_ff → stage2_ff  (dst_clk)",
    ]

    if not rows:
        lines.append("  (none detected)")
    else:
        for src_ff, src_clk, stage1_ff, stage2_ff, dst_clk in rows:
            src_clk_label  = net_names.get(src_clk,  src_clk)
            dst_clk_label  = net_names.get(dst_clk,  dst_clk)
            lines.append(
                f"  {src_ff}({src_clk_label}) → {stage1_ff} → {stage2_ff}  ({dst_clk_label})"
            )

    return lines


# ---------------------------------------------------------------------------
# Section 8: EBR Block RAM
# ---------------------------------------------------------------------------

def section_ebr(cur, bs_id, net_names=None):
    """Show block RAM port assignments grouped by block and bus role."""
    if net_names is None:
        net_names = {}
    cur.execute(
        "SELECT DISTINCT block FROM ebr_buses WHERE bitstream=%s ORDER BY block",
        (bs_id,),
    )
    blocks = [row[0] for row in cur.fetchall()]

    # Fall back to raw ebr_ports if ebr_buses is empty
    if not blocks:
        cur.execute(
            "SELECT DISTINCT block FROM ebr_ports WHERE bitstream=%s ORDER BY block",
            (bs_id,),
        )
        raw_blocks = [row[0] for row in cur.fetchall()]
        n_raw = len(raw_blocks)
        lines = [
            "",
            "── Block RAM (EBR) ─────────────────────────────────────",
            f"  {n_raw} raw EBR block(s) found  (ebr_buses not populated — run reach3.py).",
        ]
        for block in raw_blocks:
            lines.append(f"  Block {block}")
        return lines

    lines = [
        "",
        "── Block RAM (EBR) ─────────────────────────────────────",
        f"  {len(blocks)} block(s) found.",
    ]

    for block in blocks:
        lines.append(f"  Block {block}:")
        cur.execute(
            """
            SELECT bus_role, bit_index, port, net
            FROM ebr_buses WHERE bitstream=%s AND block=%s
            ORDER BY bus_role, bit_index
            """,
            (bs_id, block),
        )
        bus_rows = cur.fetchall()

        # Group by role
        by_role = {}
        for role, bit_idx, port, net in bus_rows:
            by_role.setdefault(role, []).append((bit_idx, port, net))

        role_order = ["write_data", "read_data", "write_addr", "read_addr", "ctrl"]
        for role in role_order:
            if role not in by_role:
                continue
            entries = by_role[role]
            port_strs = [
                f"{port}={net or 'NC'}"
                for _, port, net in sorted(entries)
            ]
            lines.append(f"    {role:<12}: {', '.join(port_strs)}")

        # After pass 6, shared EBR bus nets are named ebr_main_* in net_names.
        # Collect the distinct base names (strip [N] suffix) for any port nets that match.
        shared_bus_names = set()
        for role, bit_idx, port, net in bus_rows:
            if net and net in net_names:
                name = net_names[net]
                if name.startswith("ebr_main_"):
                    # Strip bit index suffix e.g. "ebr_main_write_addr[0]" → "ebr_main_write_addr"
                    base = name.split("[")[0]
                    shared_bus_names.add(base)
        if shared_bus_names:
            lines.append(f"    Shared bus nets: {', '.join(sorted(shared_bus_names))}")

    return lines


# ---------------------------------------------------------------------------
# Section 9: SPI/EFB Reachability
# ---------------------------------------------------------------------------

def section_spi_efb(cur, bs_id):
    """Show reachability from each EFB port into the fabric."""
    cur.execute(
        "SELECT port_name, net FROM efb_ports WHERE bitstream=%s ORDER BY port_name",
        (bs_id,),
    )
    efb_ports = cur.fetchall()

    lines = [
        "",
        "── SPI / EFB Reachability ──────────────────────────────",
    ]

    if not efb_ports:
        lines.append("  (no EFB ports recorded)")
        return lines

    for port_name, net in efb_ports:
        # raw nets reachable
        cur.execute(
            """
            SELECT count(*), min(min_hops), max(min_hops)
            FROM reachability WHERE bitstream=%s AND src=%s
            """,
            (bs_id, net),
        )
        r_none = cur.fetchone()
        n_none = r_none[0] if r_none else 0
        min_h_none = r_none[1] if r_none else None
        max_h_none = r_none[2] if r_none else None

        # First few reachable nets
        cur.execute(
            """
            SELECT dst FROM reachability
            WHERE bitstream=%s AND src=%s
            ORDER BY min_hops LIMIT 6
            """,
            (bs_id, net),
        )
        first_nets = [row[0] for row in cur.fetchall()]
        first_str = ", ".join(first_nets[:5])
        if len(first_nets) > 5:
            first_str += ", ..."

        # how many FF data inputs are downstream
        cur.execute(
            """
            SELECT count(*), min(r.min_hops)
            FROM reachability r
            JOIN ffs f ON f.bitstream=r.bitstream AND (f.d=r.dst OR f.ce=r.dst)
            WHERE r.bitstream=%s AND r.src=%s
            """,
            (bs_id, net),
        )
        r_ff = cur.fetchone()
        n_ff = r_ff[0] if r_ff else 0
        min_ff_hops = r_ff[1] if r_ff else None

        lines.append(f"  From {port_name} ({net}):")

        if n_none == 0:
            lines.append("    stop=none:  0 nets reachable  (hard IP only — not in fabric)")
        else:
            if min_h_none == max_h_none:
                range_str = hops_str(min_h_none)
            else:
                range_str = f"{min_h_none}–{max_h_none} hops"
            lines.append(
                f"    stop=none:  {n_none} nets reachable  ({range_str})  [{first_str}]"
            )

        if n_ff == 0:
            lines.append("    stop=FF:    0 FFs reachable")
        else:
            lines.append(
                f"    stop=FF:    {n_ff} FFs reachable   (closest: {hops_str(min_ff_hops)})"
            )

    return lines


# ---------------------------------------------------------------------------
# Section 10: Structural Patterns
# ---------------------------------------------------------------------------

def section_patterns(cur, bs_id):
    """Show detected structural patterns: shift registers, cone groups, const nets."""
    cur.execute(
        "SELECT count(*) FROM patterns WHERE bitstream=%s AND pattern_type='shift_reg'",
        (bs_id,),
    )
    n_shift = cur.fetchone()[0]

    # Cone hash groups
    cur.execute(
        """
        SELECT cone_hash, count(*) AS n_ffs, min(cone_size) AS depth
        FROM cone_hashes WHERE bitstream=%s
        GROUP BY cone_hash ORDER BY n_ffs DESC
        """,
        (bs_id,),
    )
    cone_groups = cur.fetchall()

    # Total cone_hashes
    cur.execute("SELECT count(*) FROM cone_hashes WHERE bitstream=%s", (bs_id,))
    n_cone_hashes = cur.fetchone()[0]

    # Const nets
    cur.execute("SELECT count(*) FROM const_nets WHERE bitstream=%s", (bs_id,))
    n_const = cur.fetchone()[0]

    cur.execute(
        "SELECT const_value, count(*) FROM const_nets WHERE bitstream=%s GROUP BY const_value",
        (bs_id,),
    )
    const_by_val = dict(cur.fetchall())
    n_gnd = const_by_val.get("0", 0)
    n_vcc = const_by_val.get("1", 0)

    # LUT symbolic max depth
    cur.execute(
        "SELECT max(depth) FROM lut_symbolic WHERE bitstream=%s",
        (bs_id,),
    )
    row = cur.fetchone()
    max_sym_depth = row[0] if row and row[0] is not None else 0

    cur.execute("SELECT count(*) FROM lut_symbolic WHERE bitstream=%s", (bs_id,))
    n_symbolic = cur.fetchone()[0]

    # Build readable cone group labels
    # Heuristic: group with largest n_ffs and cone_size=0 is typically CONST_D
    # The second largest with cone_size=0 is typically LEAF (ghost D input)
    cone_labels = []
    for i, (cone_hash, n_ffs, depth) in enumerate(cone_groups):
        if i == 0 and n_ffs > 100:
            label = "CONST_D"
        elif depth == 0 and n_ffs < 50:
            label = "LEAF"
        else:
            label = cone_hash[:8] + "…"
        cone_labels.append((label, n_ffs, depth))

    lines = [
        "",
        "── Structural Patterns ─────────────────────────────────",
        f"  Shift registers:  {n_shift} detected",
    ]

    if n_shift == 0:
        lines.append("    (none)")
    else:
        cur.execute(
            """
            SELECT label, detail FROM patterns
            WHERE bitstream=%s AND pattern_type='shift_reg'
            ORDER BY label
            """,
            (bs_id,),
        )
        for pat_label, detail in cur.fetchall():
            import json
            d = json.loads(detail) if isinstance(detail, str) else detail
            lines.append(
                f"    {pat_label}  len={d.get('length')}  "
                f"clk={d.get('clk_net')}  head={d.get('head_ff')}"
            )

    lines.append(f"  Cone hash groups: {len(cone_groups)} distinct structure(s)")
    for label, n_ffs, depth in cone_labels:
        lines.append(f"    {label:<12}  {n_ffs:>6} FFs  (cone_size={depth})")

    lines.append(f"  Const nets:  {n_const}")
    lines.append(f"    GND sources (const=0):  {n_gnd}")
    lines.append(f"    VCC sources (const=1):  {n_vcc}")

    lines.append(f"  LUT symbolic exprs: {n_symbolic}  (max depth {max_sym_depth})")

    return lines


# ---------------------------------------------------------------------------
# Section 11: Open Questions
# ---------------------------------------------------------------------------

def section_open_questions(cur, bs_id):
    """List open RE questions from the open_questions table."""
    cur.execute(
        """
        SELECT id, issue_num, title, status, blocker
        FROM open_questions WHERE bitstream=%s ORDER BY status, id
        """,
        (bs_id,),
    )
    questions = cur.fetchall()

    lines = [
        "",
        "── Open Questions ──────────────────────────────────────",
    ]

    if not questions:
        lines.append("  (none recorded in DB — add via annotate.py)")
        return lines

    for q_id, issue_num, title, status, blocker in questions:
        issue_str = f"  #{issue_num}" if issue_num else ""
        lines.append(f"  [{q_id}]{issue_str}  [{status}]  {title}")
        if blocker:
            lines.append(f"    blocker: {blocker}")

    return lines


# ---------------------------------------------------------------------------
# Section 12: Gaps
# ---------------------------------------------------------------------------

def section_gaps(cur, bs_id):
    """Enumerate what's still unknown or unresolved — the 'what we don't know' list."""
    cur.execute(
        "SELECT count(*) FROM pad_map WHERE bitstream=%s AND net_in IS NULL AND net_out IS NULL",
        (bs_id,),
    )
    n_unresolved_pads = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM nets WHERE bitstream=%s", (bs_id,))
    n_nets = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM net_names WHERE bitstream=%s", (bs_id,))
    n_named = cur.fetchone()[0]
    n_unnamed_nets = n_nets - n_named
    pct_unnamed = 100.0 * n_unnamed_nets / n_nets if n_nets else 0.0

    cur.execute("SELECT count(*) FROM ffs WHERE bitstream=%s", (bs_id,))
    n_ffs = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM luts WHERE bitstream=%s", (bs_id,))
    n_luts = cur.fetchone()[0]
    n_cells = n_ffs + n_luts

    cur.execute("SELECT count(*) FROM cell_names WHERE bitstream=%s", (bs_id,))
    n_named_cells = cur.fetchone()[0]
    n_unnamed_cells = n_cells - n_named_cells
    pct_unnamed_cells = 100.0 * n_unnamed_cells / n_cells if n_cells else 0.0

    # Active FFs with ghost D inputs (fanin=0)
    cur.execute(
        """
        SELECT count(*) FROM ffs f
        JOIN net_stats ns ON ns.bitstream=f.bitstream AND ns.net=f.d
        WHERE f.bitstream=%s AND f.d != '1''b0' AND ns.fanin=0
        """,
        (bs_id,),
    )
    n_ghost_d = cur.fetchone()[0]

    # Clock domains count (all are ghost clock nets — hard IP spine)
    cur.execute(
        "SELECT count(DISTINCT clk_net) FROM clock_domains WHERE bitstream=%s",
        (bs_id,),
    )
    n_clk_domains = cur.fetchone()[0]

    # Total crossings
    cur.execute("SELECT count(*) FROM clock_crossings WHERE bitstream=%s", (bs_id,))
    n_crossings = cur.fetchone()[0]

    # Verified synchroniser count (pass 9) — zero if table doesn't exist yet
    n_verified = 0
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'cdc_synchronisers'
        )
        """
    )
    if cur.fetchone()[0]:
        cur.execute(
            "SELECT count(*) FROM cdc_synchronisers WHERE bitstream=%s",
            (bs_id,),
        )
        n_verified = cur.fetchone()[0]
    n_unverified = n_crossings - n_verified

    lines = [
        "",
        "── Gaps ────────────────────────────────────────────────",
        f"  {n_unresolved_pads} pads unresolved  (CIB bug #57)",
        f"  {n_unnamed_nets} nets unnamed  ({pct_unnamed:.1f}%)",
        f"  {n_unnamed_cells} cells unnamed  ({pct_unnamed_cells:.1f}%)",
        f"  {n_ghost_d} FF D-inputs are ghost nets  (hard IP, not modelled in netlist)",
        f"  {n_clk_domains} clock nets unresolved to source  (PLL / CLKDIV / GSI — hard IP spine)",
        f"  {n_crossings} clock crossings  ({n_verified} verified as synchronisers, {n_unverified} unverified)",
    ]
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Parse args, connect to DB, run all sections, print or write report."""
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--bitstream",
        default="V07",
        help="Bitstream label to report on (default: V07)",
    )
    ap.add_argument(
        "--out",
        default=None,
        metavar="FILE",
        help="Write report to FILE instead of stdout",
    )
    args = ap.parse_args()

    conn = connect()
    cur  = conn.cursor()

    cur.execute("SELECT id FROM bitstreams WHERE label=%s", (args.bitstream,))
    row = cur.fetchone()
    if not row:
        die(f"Bitstream {args.bitstream!r} not found — run load.py first")
    bs_id = row[0]

    # Fetch shared lookup once — reused by many sections
    net_names = _fetch_net_names(cur, bs_id)

    # Run all sections in order
    sections = [
        section_header(cur, bs_id),
        section_netlist(cur, bs_id),
        section_clocks(cur, bs_id, net_names),
        section_boundary(cur, bs_id, net_names),
        section_active_ffs(cur, bs_id, net_names),
        section_register_clusters(cur, bs_id, net_names),
        section_clock_crossings(cur, bs_id, net_names),
        section_cdc_synchronisers(cur, bs_id, net_names),
        section_ebr(cur, bs_id, net_names),
        section_spi_efb(cur, bs_id),
        section_patterns(cur, bs_id),
        section_open_questions(cur, bs_id),
        section_gaps(cur, bs_id),
    ]

    cur.close()
    conn.close()

    lines = []
    for section in sections:
        lines.extend(section)
    lines.append("")  # trailing newline

    report_text = "\n".join(lines)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(report_text, encoding="utf-8")
        print(f"Report written to {out_path}", file=sys.stderr)
    else:
        print(report_text)


if __name__ == "__main__":
    main()
