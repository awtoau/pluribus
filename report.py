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
import schema
from db import engine, die, BACKEND

from sqlalchemy import select, func, and_, or_, text, distinct


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


def _fetch_net_names(conn, bs_id):
    """Return {net: name} dict for all named nets in this bitstream."""
    nn = schema.net_names
    rows = conn.execute(
        select(nn.c.net, nn.c.name).where(nn.c.bitstream == bs_id)
    ).fetchall()
    return dict(rows)


def _table_exists(conn, table_name):
    """Return True if the given table name exists in the DB."""
    if BACKEND == "postgres":
        row = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                " WHERE table_name = :t)"
            ),
            {"t": table_name},
        ).fetchone()
        return bool(row[0])
    else:
        row = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM sqlite_master"
                " WHERE type='table' AND name = :t)"
            ),
            {"t": table_name},
        ).fetchone()
        return bool(row[0])


# ---------------------------------------------------------------------------
# Section 1: Header
# ---------------------------------------------------------------------------

def section_header(conn, bs_id):
    """Print the report header with bitstream metadata and generation timestamp."""
    bs = schema.bitstreams
    row = conn.execute(
        select(bs.c.label, bs.c.device, bs.c.package, bs.c.loaded_at)
        .where(bs.c.id == bs_id)
    ).fetchone()
    label, device, package, loaded_at = row

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

def section_netlist(conn, bs_id):
    """Summarise the raw netlist: FF/LUT/net counts, naming coverage, clocks."""
    ffs = schema.ffs
    luts = schema.luts
    nets = schema.nets
    nf = schema.net_fanout
    ns = schema.net_stats
    nn = schema.net_names
    cn = schema.cell_names
    cd = schema.clock_domains
    co = schema.const_nets

    n_ffs = conn.execute(
        select(func.count()).where(ffs.c.bitstream == bs_id)
    ).scalar()

    n_luts = conn.execute(
        select(func.count()).where(luts.c.bitstream == bs_id)
    ).scalar()

    n_nets = conn.execute(
        select(func.count()).where(nets.c.bitstream == bs_id)
    ).scalar()

    n_fanout = conn.execute(
        select(func.count()).where(nf.c.bitstream == bs_id)
    ).scalar()

    row = conn.execute(
        select(func.avg(ns.c.fanout), func.max(ns.c.fanout))
        .where(ns.c.bitstream == bs_id)
    ).fetchone()
    avg_fo = float(row[0]) if row[0] is not None else 0.0
    max_fo = row[1] or 0

    n_named_nets = conn.execute(
        select(func.count()).where(nn.c.bitstream == bs_id)
    ).scalar()
    pct_nets = 100.0 * n_named_nets / n_nets if n_nets else 0.0

    n_named_cells = conn.execute(
        select(func.count()).where(cn.c.bitstream == bs_id)
    ).scalar()
    n_cells = n_ffs + n_luts
    pct_cells = 100.0 * n_named_cells / n_cells if n_cells else 0.0

    n_clk_domains = conn.execute(
        select(func.count(distinct(cd.c.clk_net)))
        .where(cd.c.bitstream == bs_id)
    ).scalar()

    n_active_ffs = conn.execute(
        select(func.count()).where(
            and_(ffs.c.bitstream == bs_id, ffs.c.d != "1'b0")
        )
    ).scalar()
    n_stuck_ffs = n_ffs - n_active_ffs

    n_const_nets = conn.execute(
        select(func.count()).where(co.c.bitstream == bs_id)
    ).scalar()

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

def section_clocks(conn, bs_id, net_names):
    """List clock domains ranked by FF count with crossing counts."""
    cd = schema.clock_domains
    cc = schema.clock_crossings

    domains = conn.execute(
        select(cd.c.clk_net, func.count().label("n_ffs"))
        .where(cd.c.bitstream == bs_id)
        .group_by(cd.c.clk_net)
        .order_by(func.count().desc())
    ).fetchall()

    crossings_in = dict(conn.execute(
        select(cc.c.dst_clk, func.count())
        .where(cc.c.bitstream == bs_id)
        .group_by(cc.c.dst_clk)
    ).fetchall())

    crossings_out = dict(conn.execute(
        select(cc.c.src_clk, func.count())
        .where(cc.c.bitstream == bs_id)
        .group_by(cc.c.src_clk)
    ).fetchall())

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

def section_boundary(conn, bs_id, net_names):
    """Summarise the physical pad map and EFB ports."""
    pm = schema.pad_map
    ffs = schema.ffs
    luts = schema.luts
    cn = schema.cell_names
    ep = schema.efb_ports
    r = schema.reachability
    nf = schema.net_fanout

    n_total_pads = conn.execute(
        select(func.count()).where(pm.c.bitstream == bs_id)
    ).scalar()

    n_resolved = conn.execute(
        select(func.count()).where(
            and_(
                pm.c.bitstream == bs_id,
                or_(pm.c.net_in.isnot(None), pm.c.net_out.isnot(None)),
            )
        )
    ).scalar()
    n_unresolved = n_total_pads - n_resolved

    input_pads = conn.execute(
        select(pm.c.pin, pm.c.label, pm.c.net_in)
        .where(and_(pm.c.bitstream == bs_id, pm.c.net_in.isnot(None)))
        .order_by(pm.c.pin)
    ).fetchall()

    output_pads = conn.execute(
        select(pm.c.pin, pm.c.label, pm.c.net_out)
        .where(and_(pm.c.bitstream == bs_id, pm.c.net_out.isnot(None)))
        .order_by(pm.c.pin)
    ).fetchall()

    efb_ports = conn.execute(
        select(ep.c.port_name, ep.c.net)
        .where(ep.c.bitstream == bs_id)
        .order_by(ep.c.port_name)
    ).fetchall()

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
        # reachability stats — join reachability with ffs on D or CE
        reach_row = conn.execute(
            select(func.count(), func.min(r.c.min_hops))
            .select_from(
                r.join(ffs, and_(
                    ffs.c.bitstream == r.c.bitstream,
                    or_(ffs.c.d == r.c.dst, ffs.c.ce == r.c.dst),
                ))
            )
            .where(and_(r.c.bitstream == bs_id, r.c.src == net))
        ).fetchone()
        n_ffs_reach = reach_row[0] if reach_row else 0
        min_hops = reach_row[1] if reach_row else None

        hop_str = f"{n_ffs_reach} FFs in {hops_str(min_hops)}" if min_hops is not None else "no reach data"
        name = net_names.get(net, label)
        lines.append(f"    {name:<12}  pin{pin:<4}  {net:<8}  → reach: {hop_str}")

    if not input_pads:
        lines.append("    (none)")

    lines.append("")
    lines.append(f"  Outputs ({len(output_pads)} pads with net_out):")

    for pin, label, net in output_pads:
        # Find what drives the net (FF or LUT)
        ff_row = conn.execute(
            select(ffs.c.cell, ffs.c.clk)
            .where(and_(ffs.c.bitstream == bs_id, ffs.c.q == net))
        ).fetchone()
        if ff_row:
            ff_cell, clk = ff_row
            cn_row = conn.execute(
                select(cn.c.name)
                .where(and_(cn.c.bitstream == bs_id, cn.c.cell == ff_cell))
            ).fetchone()
            ff_label = cn_row[0] if cn_row else ff_cell
            driver_str = f"ff={ff_label}  clk={net_with_name(clk, net_names)}"
        else:
            lut_row = conn.execute(
                select(luts.c.cell, luts.c.fn)
                .where(and_(luts.c.bitstream == bs_id, luts.c.z == net))
            ).fetchone()
            if lut_row:
                driver_str = f"lut={lut_row[0]}  fn={lut_row[1]}"
            else:
                driver_str = "unknown driver"
        name = net_names.get(net, label)
        lines.append(f"    {name:<12}  pin{pin:<4}  {net:<8}  ← {driver_str}")

    if not output_pads:
        lines.append("    (none)")

    lines.append("")
    lines.append(f"  EFB ports ({len(efb_ports)}):")

    for port_name, net in efb_ports:
        fo = conn.execute(
            select(func.count())
            .where(and_(nf.c.bitstream == bs_id, nf.c.net == net))
        ).scalar()

        reach_row = conn.execute(
            select(func.count(), func.min(r.c.min_hops))
            .select_from(
                r.join(ffs, and_(
                    ffs.c.bitstream == r.c.bitstream,
                    or_(ffs.c.d == r.c.dst, ffs.c.ce == r.c.dst),
                ))
            )
            .where(and_(r.c.bitstream == bs_id, r.c.src == net))
        ).fetchone()
        n_ff_reach = reach_row[0] if reach_row else 0
        min_hops = reach_row[1] if reach_row else None

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

def section_active_ffs(conn, bs_id, net_names):
    """Detail the non-reset FFs — the only FFs doing actual work."""
    ffs = schema.ffs
    fd = schema.ff_d_functions
    ns = schema.net_stats
    nn = schema.net_names
    pfi = schema.pad_ff_influence
    cc = schema.clock_crossings

    active = conn.execute(
        select(ffs.c.cell, ffs.c.clk, ffs.c.ce, ffs.c.d, ffs.c.q)
        .where(and_(ffs.c.bitstream == bs_id, ffs.c.d != "1'b0"))
        .order_by(ffs.c.cell)
    ).fetchall()

    lines = [
        "",
        f"── Active Flip-Flops ({len(active)}) ───────────────────────────",
        "  These FFs have real D inputs — the active logic in this design.",
    ]

    for ff_cell, clk, ce, d_net, q_net in active:

        fn_row = conn.execute(
            select(fd.c.fn_expr).where(fd.c.ff_cell == ff_cell)
        ).fetchone()
        fn_expr = fn_row[0] if fn_row else d_net

        ns_row = conn.execute(
            select(ns.c.fanin)
            .where(and_(ns.c.bitstream == bs_id, ns.c.net == d_net))
        ).fetchone()
        fanin = ns_row[0] if ns_row else None

        if fanin == 0:
            nn_row = conn.execute(
                select(nn.c.name, nn.c.source)
                .where(and_(nn.c.bitstream == bs_id, nn.c.net == d_net))
            ).fetchone()
            if nn_row and nn_row[1] != 'auto_ghost':
                d_annotation = f"{d_net}  (ghost net — fanin=0, hard IP source; resolved: {nn_row[0]})"
            else:
                d_annotation = f"{d_net}  (ghost net — fanin=0, hard IP source)"
        else:
            d_annotation = fn_expr or d_net

        # Pad influence — collect pad_labels as a list
        pad_rows = conn.execute(
            select(pfi.c.pad_label)
            .where(and_(pfi.c.bitstream == bs_id, pfi.c.ff_cell == ff_cell))
            .order_by(pfi.c.pad_label)
        ).fetchall()
        pad_labels = [row[0] for row in pad_rows]
        pad_str = ", ".join(pad_labels) if pad_labels else "none"

        n_cross = conn.execute(
            select(func.count(distinct(cc.c.dst_clk)))
            .where(and_(cc.c.bitstream == bs_id, cc.c.src_ff == ff_cell))
        ).scalar()

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

def section_register_clusters(conn, bs_id, net_names):
    """Group FFs by tile location to identify register banks."""
    ffs = schema.ffs

    # Tile extraction uses dialect-specific string functions; use text() for
    # this purely analytic, read-only section.
    if BACKEND == "postgres":
        clusters = conn.execute(
            text(
                "SELECT substring(cell, 1, length(cell)-3) AS tile,"
                " count(*) AS n_ffs,"
                " array_agg(DISTINCT clk) AS clks,"
                " array_agg(DISTINCT ce) AS ces"
                " FROM ffs WHERE bitstream=:bs"
                " GROUP BY tile ORDER BY n_ffs DESC, tile"
            ),
            {"bs": bs_id},
        ).fetchall()

        n_tiles = conn.execute(
            text(
                "SELECT count(DISTINCT substring(cell, 1, length(cell)-3))"
                " FROM ffs WHERE bitstream=:bs"
            ),
            {"bs": bs_id},
        ).scalar()

        mixed_clock = conn.execute(
            text(
                "SELECT substring(cell, 1, length(cell)-3) AS tile,"
                " array_agg(DISTINCT clk) AS clks,"
                " count(*) AS n_ffs"
                " FROM ffs WHERE bitstream=:bs"
                " GROUP BY tile HAVING count(DISTINCT clk) > 1"
                " ORDER BY tile"
            ),
            {"bs": bs_id},
        ).fetchall()
    else:
        # SQLite uses substr() not substring()
        clusters = conn.execute(
            text(
                "SELECT substr(cell, 1, length(cell)-3) AS tile,"
                " count(*) AS n_ffs,"
                " group_concat(DISTINCT clk) AS clks,"
                " group_concat(DISTINCT ce) AS ces"
                " FROM ffs WHERE bitstream=:bs"
                " GROUP BY tile ORDER BY n_ffs DESC, tile"
            ),
            {"bs": bs_id},
        ).fetchall()

        n_tiles = conn.execute(
            text(
                "SELECT count(DISTINCT substr(cell, 1, length(cell)-3))"
                " FROM ffs WHERE bitstream=:bs"
            ),
            {"bs": bs_id},
        ).scalar()

        mixed_clock = conn.execute(
            text(
                "SELECT substr(cell, 1, length(cell)-3) AS tile,"
                " group_concat(DISTINCT clk) AS clks,"
                " count(*) AS n_ffs"
                " FROM ffs WHERE bitstream=:bs"
                " GROUP BY tile HAVING count(DISTINCT clk) > 1"
                " ORDER BY tile"
            ),
            {"bs": bs_id},
        ).fetchall()

    n_total_ffs = conn.execute(
        select(func.count()).where(ffs.c.bitstream == bs_id)
    ).scalar()

    lines = [
        "",
        "── Register Clusters ───────────────────────────────────",
        f"  {n_tiles} tile groups, {n_total_ffs} FFs total",
        "",
        "  Largest groups (8 FFs per full tile):",
    ]

    def _split_agg(val):
        """Normalise array_agg (list) or group_concat (str) to a Python list."""
        if val is None:
            return []
        if isinstance(val, list):
            return val
        return val.split(",")

    for row in clusters[:20]:
        tile, n_ffs, clks_raw, ces_raw = row[0], row[1], row[2], row[3]
        clks = _split_agg(clks_raw)
        ces  = _split_agg(ces_raw)
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
    for row in mixed_clock[:20]:
        tile, clks_raw, n_ffs = row[0], row[1], row[2]
        clks = _split_agg(clks_raw)
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

def section_clock_crossings(conn, bs_id, net_names):
    """Summarise potential metastability hazards across clock domains."""
    cc = schema.clock_crossings

    n_total = conn.execute(
        select(func.count()).where(cc.c.bitstream == bs_id)
    ).scalar()

    top_pairs = conn.execute(
        select(cc.c.src_clk, cc.c.dst_clk, func.count().label("n"))
        .where(cc.c.bitstream == bs_id)
        .group_by(cc.c.src_clk, cc.c.dst_clk)
        .order_by(func.count().desc())
        .limit(15)
    ).fetchall()

    dangerous = conn.execute(
        select(cc.c.dst_ff, cc.c.dst_clk, func.count(distinct(cc.c.src_clk)).label("n_srcs"))
        .where(cc.c.bitstream == bs_id)
        .group_by(cc.c.dst_ff, cc.c.dst_clk)
        .order_by(func.count(distinct(cc.c.src_clk)).desc())
        .limit(10)
    ).fetchall()

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

def section_cdc_synchronisers(conn, bs_id, net_names):
    """List detected 2-FF CDC synchroniser chains (named by pass 9 of reach4)."""
    if not _table_exists(conn, "cdc_synchronisers"):
        return [
            "",
            "── CDC Synchronisers ────────────────────────────────────",
            "  (cdc_synchronisers table not found — run reach4 pass 9)",
        ]

    cs = schema.cdc_synchronisers

    rows = conn.execute(
        select(cs.c.src_ff, cs.c.src_clk, cs.c.stage1_ff, cs.c.stage2_ff, cs.c.dst_clk)
        .where(cs.c.bitstream == bs_id)
        .order_by(cs.c.dst_clk, cs.c.src_clk)
    ).fetchall()
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
            src_clk_label = net_names.get(src_clk, src_clk)
            dst_clk_label = net_names.get(dst_clk, dst_clk)
            lines.append(
                f"  {src_ff}({src_clk_label}) → {stage1_ff} → {stage2_ff}  ({dst_clk_label})"
            )

    return lines


# ---------------------------------------------------------------------------
# Section 8: EBR Block RAM
# ---------------------------------------------------------------------------

def section_ebr(conn, bs_id, net_names=None):
    """Show block RAM port assignments grouped by block and bus role."""
    if net_names is None:
        net_names = {}

    eb = schema.ebr_buses
    ep = schema.ebr_ports

    blocks = [
        row[0] for row in conn.execute(
            select(distinct(eb.c.block))
            .where(eb.c.bitstream == bs_id)
            .order_by(eb.c.block)
        ).fetchall()
    ]

    if not blocks:
        raw_blocks = [
            row[0] for row in conn.execute(
                select(distinct(ep.c.block))
                .where(ep.c.bitstream == bs_id)
                .order_by(ep.c.block)
            ).fetchall()
        ]
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
        bus_rows = conn.execute(
            select(eb.c.bus_role, eb.c.bit_index, eb.c.port, eb.c.net)
            .where(and_(eb.c.bitstream == bs_id, eb.c.block == block))
            .order_by(eb.c.bus_role, eb.c.bit_index)
        ).fetchall()

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

        shared_bus_names = set()
        for role, bit_idx, port, net in bus_rows:
            if net and net in net_names:
                name = net_names[net]
                if name.startswith("ebr_main_"):
                    base = name.split("[")[0]
                    shared_bus_names.add(base)
        if shared_bus_names:
            lines.append(f"    Shared bus nets: {', '.join(sorted(shared_bus_names))}")

    return lines


# ---------------------------------------------------------------------------
# Section 9: SPI/EFB Reachability
# ---------------------------------------------------------------------------

def section_spi_efb(conn, bs_id):
    """Show reachability from each EFB port into the fabric."""
    ep = schema.efb_ports
    r  = schema.reachability
    ffs = schema.ffs

    efb_ports = conn.execute(
        select(ep.c.port_name, ep.c.net)
        .where(ep.c.bitstream == bs_id)
        .order_by(ep.c.port_name)
    ).fetchall()

    lines = [
        "",
        "── SPI / EFB Reachability ──────────────────────────────",
    ]

    if not efb_ports:
        lines.append("  (no EFB ports recorded)")
        return lines

    for port_name, net in efb_ports:
        r_none = conn.execute(
            select(func.count(), func.min(r.c.min_hops), func.max(r.c.min_hops))
            .where(and_(r.c.bitstream == bs_id, r.c.src == net))
        ).fetchone()
        n_none    = r_none[0] if r_none else 0
        min_h_none = r_none[1] if r_none else None
        max_h_none = r_none[2] if r_none else None

        first_rows = conn.execute(
            select(r.c.dst)
            .where(and_(r.c.bitstream == bs_id, r.c.src == net))
            .order_by(r.c.min_hops)
            .limit(6)
        ).fetchall()
        first_nets = [row[0] for row in first_rows]
        first_str = ", ".join(first_nets[:5])
        if len(first_nets) > 5:
            first_str += ", ..."

        r_ff = conn.execute(
            select(func.count(), func.min(r.c.min_hops))
            .select_from(
                r.join(ffs, and_(
                    ffs.c.bitstream == r.c.bitstream,
                    or_(ffs.c.d == r.c.dst, ffs.c.ce == r.c.dst),
                ))
            )
            .where(and_(r.c.bitstream == bs_id, r.c.src == net))
        ).fetchone()
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

def section_patterns(conn, bs_id):
    """Show detected structural patterns: shift registers, cone groups, const nets."""
    pat = schema.patterns
    ch  = schema.cone_hashes
    co  = schema.const_nets
    ls  = schema.lut_symbolic

    n_shift = conn.execute(
        select(func.count())
        .where(and_(pat.c.bitstream == bs_id, pat.c.pattern_type == "shift_reg"))
    ).scalar()

    cone_groups = conn.execute(
        select(ch.c.cone_hash, func.count().label("n_ffs"), func.min(ch.c.cone_size).label("depth"))
        .where(ch.c.bitstream == bs_id)
        .group_by(ch.c.cone_hash)
        .order_by(func.count().desc())
    ).fetchall()

    n_const = conn.execute(
        select(func.count()).where(co.c.bitstream == bs_id)
    ).scalar()

    const_by_val = dict(conn.execute(
        select(co.c.const_value, func.count())
        .where(co.c.bitstream == bs_id)
        .group_by(co.c.const_value)
    ).fetchall())
    n_gnd = const_by_val.get("0", 0)
    n_vcc = const_by_val.get("1", 0)

    row = conn.execute(
        select(func.max(ls.c.depth)).where(ls.c.bitstream == bs_id)
    ).fetchone()
    max_sym_depth = row[0] if row and row[0] is not None else 0

    n_symbolic = conn.execute(
        select(func.count()).where(ls.c.bitstream == bs_id)
    ).scalar()

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
        shift_rows = conn.execute(
            select(pat.c.label, pat.c.detail)
            .where(and_(pat.c.bitstream == bs_id, pat.c.pattern_type == "shift_reg"))
            .order_by(pat.c.label)
        ).fetchall()
        for pat_label, detail in shift_rows:
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

def section_open_questions(conn, bs_id):
    """List open RE questions from the open_questions table."""
    oq = schema.open_questions

    questions = conn.execute(
        select(oq.c.id, oq.c.issue_num, oq.c.title, oq.c.status, oq.c.blocker)
        .where(oq.c.bitstream == bs_id)
        .order_by(oq.c.status, oq.c.id)
    ).fetchall()

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

def section_gaps(conn, bs_id):
    """Enumerate what's still unknown or unresolved — the 'what we don't know' list."""
    pm   = schema.pad_map
    nets = schema.nets
    nn   = schema.net_names
    ffs  = schema.ffs
    luts = schema.luts
    cn   = schema.cell_names
    ns   = schema.net_stats
    cd   = schema.clock_domains
    cc   = schema.clock_crossings

    n_unresolved_pads = conn.execute(
        select(func.count()).where(
            and_(
                pm.c.bitstream == bs_id,
                pm.c.net_in.is_(None),
                pm.c.net_out.is_(None),
            )
        )
    ).scalar()

    n_nets = conn.execute(
        select(func.count()).where(nets.c.bitstream == bs_id)
    ).scalar()

    n_named = conn.execute(
        select(func.count()).where(nn.c.bitstream == bs_id)
    ).scalar()
    n_unnamed_nets = n_nets - n_named
    pct_unnamed = 100.0 * n_unnamed_nets / n_nets if n_nets else 0.0

    n_ffs = conn.execute(
        select(func.count()).where(ffs.c.bitstream == bs_id)
    ).scalar()
    n_luts = conn.execute(
        select(func.count()).where(luts.c.bitstream == bs_id)
    ).scalar()
    n_cells = n_ffs + n_luts

    n_named_cells = conn.execute(
        select(func.count()).where(cn.c.bitstream == bs_id)
    ).scalar()
    n_unnamed_cells = n_cells - n_named_cells
    pct_unnamed_cells = 100.0 * n_unnamed_cells / n_cells if n_cells else 0.0

    # Active FFs with ghost D inputs (fanin=0)
    n_ghost_d = conn.execute(
        select(func.count())
        .select_from(
            ffs.join(ns, and_(ns.c.bitstream == ffs.c.bitstream, ns.c.net == ffs.c.d))
        )
        .where(and_(
            ffs.c.bitstream == bs_id,
            ffs.c.d != "1'b0",
            ns.c.fanin == 0,
        ))
    ).scalar()

    n_clk_domains = conn.execute(
        select(func.count(distinct(cd.c.clk_net)))
        .where(cd.c.bitstream == bs_id)
    ).scalar()

    n_crossings = conn.execute(
        select(func.count()).where(cc.c.bitstream == bs_id)
    ).scalar()

    n_verified = 0
    if _table_exists(conn, "cdc_synchronisers"):
        cs = schema.cdc_synchronisers
        n_verified = conn.execute(
            select(func.count()).where(cs.c.bitstream == bs_id)
        ).scalar()
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

    bs_tbl = schema.bitstreams

    with engine().connect() as conn:
        row = conn.execute(
            select(bs_tbl.c.id).where(bs_tbl.c.label == args.bitstream)
        ).fetchone()
        if not row:
            die(f"Bitstream {args.bitstream!r} not found — run load.py first")
        bs_id = row[0]

        # Fetch shared lookup once — reused by many sections
        net_names = _fetch_net_names(conn, bs_id)

        # Run all sections in order
        sections = [
            section_header(conn, bs_id),
            section_netlist(conn, bs_id),
            section_clocks(conn, bs_id, net_names),
            section_boundary(conn, bs_id, net_names),
            section_active_ffs(conn, bs_id, net_names),
            section_register_clusters(conn, bs_id, net_names),
            section_clock_crossings(conn, bs_id, net_names),
            section_cdc_synchronisers(conn, bs_id, net_names),
            section_ebr(conn, bs_id, net_names),
            section_spi_efb(conn, bs_id),
            section_patterns(conn, bs_id),
            section_open_questions(conn, bs_id),
            section_gaps(conn, bs_id),
        ]

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
