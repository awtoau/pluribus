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
    """Return {net: name} for all named nets — non-confirmed names get a
    `spec_` prefix (matching the recovered Verilog) so guesses read as guesses.
    """
    nn = schema.net_names
    rows = conn.execute(
        select(nn.c.net, nn.c.name, nn.c.confidence).where(nn.c.bitstream == bs_id)
    ).fetchall()
    return {net: (name if conf == "confirmed" else f"spec_{name}")
            for net, name, conf in rows}


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


def section_config_summary(conn, bs_id, net_names):
    """Top-down device-configuration overview — the one-screen 'how is this
    device configured' view, synthesised from the recovered netlist + hard-IP
    config.  The detailed sections below expand each line.
    """
    import collections, re
    ffs, luts, nets = schema.ffs, schema.luts, schema.nets
    cds, nn = schema.clock_domain_summary, schema.net_names

    n_ff = conn.execute(select(func.count()).where(ffs.c.bitstream == bs_id)).scalar()
    n_lut = conn.execute(select(func.count()).where(luts.c.bitstream == bs_id)).scalar()
    n_net = conn.execute(select(func.count()).where(nets.c.bitstream == bs_id)).scalar()

    # Naming confidence — the vast majority of names are inferences, not facts.
    conf = dict(conn.execute(
        select(nn.c.confidence, func.count())
        .where(nn.c.bitstream == bs_id).group_by(nn.c.confidence)).fetchall())
    n_named = sum(conf.values())
    n_confirmed = conf.get("confirmed", 0)

    # Device EBR-block budget (MachXO2 datasheet) for a utilisation figure.
    device = conn.execute(
        select(schema.bitstreams.c.device).where(schema.bitstreams.c.id == bs_id)).scalar()
    _MACHXO2_EBR = {"256": 0, "640": 2, "1200": 7, "2000": 8, "4000": 10, "7000": 26}
    _MACHXO2_LUT = {"256": 256, "640": 640, "1200": 1280, "2000": 2112,
                    "4000": 4320, "7000": 6864}
    _m = re.search(r"(\d{3,4})", device or "")
    dev_ebr = _MACHXO2_EBR.get(_m.group(1)) if _m else None
    dev_lut = _MACHXO2_LUT.get(_m.group(1)) if _m else None
    EBR_BITS = 9216  # one MachXO2 EBR block = 1024 × 9 bits = 9 Kbit

    # Clocking: domains grouped by recovered frequency.  The frequency lives on
    # the named spine net; most domains' direct clock net is unlabelled.
    clk_nets = [r[0] for r in conn.execute(
        select(cds.c.clk_net).where(cds.c.bitstream == bs_id)).fetchall()]
    freq_by_net = dict(conn.execute(
        select(nn.c.net, nn.c.freq_mhz).where(
            and_(nn.c.bitstream == bs_id, nn.c.freq_mhz.isnot(None)))).fetchall())
    freq_counts = collections.Counter(freq_by_net.get(n) for n in clk_nets)
    n_dom = len(clk_nets)
    unknown = freq_counts.pop(None, 0)
    freq_bits = [f"{f:g} MHz×{c}" for f, c in sorted(freq_counts.items())]

    # Hard IP: EFB config + EBR blocks (preloaded vs blank/runtime-loaded).
    efb = conn.execute(
        select(schema.efb_config.c.kind, schema.efb_config.c.sel)
        .where(schema.efb_config.c.bitstream == bs_id)).fetchall()
    def _blk_key(b):
        m = re.match(r"R(\d+)C(\d+)", b)
        return (int(m.group(1)), int(m.group(2))) if m else (99, 99)
    ebr_blocks = sorted({r[0] for r in conn.execute(
        select(schema.ebr_ports.c.block).where(
            schema.ebr_ports.c.bitstream == bs_id)).fetchall()}, key=_blk_key)
    initb = {r.block: r for r in conn.execute(
        select(schema.ebr_init_blocks.c.block, schema.ebr_init_blocks.c.wid,
               schema.ebr_init_blocks.c.mode, schema.ebr_init_blocks.c.data_width,
               schema.ebr_init_blocks.c.n_nonzero)
        .where(schema.ebr_init_blocks.c.bitstream == bs_id)).fetchall()}
    n_preloaded = sum(1 for b in ebr_blocks if b in initb and initb[b].n_nonzero > 0)

    # Generic content characterisation from the recovered words: a small set of
    # evenly-spaced levels is a staircase RAMP (a datapath self-test pattern,
    # overwritten at runtime), not operational data.
    dvals = collections.defaultdict(set)
    for blk, w in conn.execute(
        select(schema.ebr_init.c.block, schema.ebr_init.c.word9).distinct()
        .where(schema.ebr_init.c.bitstream == bs_id)).fetchall():
        dvals[blk].add(w)

    def _ebr_content(b):
        # Raw physical words only; the doc's per-read-width "levels" needs
        # LSB-first unpacking we don't do here, so report the pattern, not a
        # (misleading) level count.  A handful of distinct values across 1K
        # words is a patterned prefill, read out first = a self-test pattern.
        vals = [v for v in dvals.get(b, set()) if v is not None]
        if not any(vals):
            return "runtime buffer (blank)"
        if len(vals) <= 16:
            return "1st-read self-test pattern (staircase)"
        return "prefilled data"

    # I/O peripherals grouped by pad-label prefix (board annotations).
    pads = conn.execute(
        select(schema.pad_map.c.label, schema.pad_map.c.direction)
        .where(schema.pad_map.c.bitstream == bs_id)).fetchall()
    groups = collections.defaultdict(lambda: [0, set()])
    for lbl, direction in pads:
        if not lbl:
            continue
        pre = (lbl.split("_")[0] if "_" in lbl
               else "".join(c for c in lbl if not c.isdigit()) or lbl)
        groups[pre][0] += 1
        if direction:
            groups[pre][1].add(direction)

    lines = [
        "",
        "── Device Configuration (top-down) ─────────────────────",
        f"  Fabric:    {n_lut}"
        + (f"/{dev_lut} ({100 * n_lut // dev_lut}%)" if dev_lut else "")
        + f" LUTs, {n_ff} FFs, {n_net} nets",
        f"  Names:     {n_named}/{n_net} named, but only {n_confirmed} CONFIRMED"
        f" ({conf.get('estimate', 0)} spatial-est, {conf.get('inferred', 0)} inferred,"
        f" {conf.get('guess', 0) + conf.get('speculative', 0)} guess/spec) —"
        f" clock names/freqs and most functional names are INFERENCES, not facts",
        f"  Clocking:  {n_dom} domains"
        + (f" — {', '.join(freq_bits)}" if freq_bits else "")
        + (f", {unknown} unlabelled" if unknown else ""),
        "             driven off-fabric by PLL/OSC/DCC hard IP via the HPBX spine",
    ]
    if efb:
        lines.append("  EFB:       "
                     + ", ".join(f"{k} (sel 0x{s:02x})" for k, s in efb))
    else:
        lines.append("  EFB:       no config recovered (truncated .config? see #54)")
    ebr_kbit = len(ebr_blocks) * EBR_BITS / 1024
    ebr_kb = len(ebr_blocks) * EBR_BITS / 8 / 1024
    util = (f" of {dev_ebr} ({100 * len(ebr_blocks) // dev_ebr}%)"
            if dev_ebr else "")
    lines.append(f"  Block RAM: {len(ebr_blocks)} EBR blocks{util} = "
                 f"{ebr_kbit:.0f} Kbit ({ebr_kb:.1f} KB) — "
                 f"{n_preloaded} prefilled, {len(ebr_blocks) - n_preloaded} blank")
    lines.append(f"             {'block':<7} {'WID':<4} {'mode':<8} {'width':<6} content")
    for b in ebr_blocks:
        ib = initb.get(b)
        wid = str(ib.wid) if ib else "—"
        mode = ib.mode if ib else "—"
        width = f"x{ib.data_width}" if ib else "—"
        lines.append(f"             {b:<7} {wid:<4} {mode:<8} {width:<6} {_ebr_content(b)}")
    if n_preloaded:
        kb = n_preloaded * 1152 / 1024
        lines.append(f"             prefill costs ~{kb:.1f} KB of bitstream "
                     f"(init is per-block optional — blank blocks are omitted)")
    if groups:
        lines.append("  I/O (from pad annotations):")
        lines.append(f"             {'group':<8} {'pins':>5}  dir")
        for pre, (cnt, dirs) in sorted(groups.items(), key=lambda x: -x[1][0]):
            lines.append(f"             {pre:<8} {cnt:>5}  {'/'.join(sorted(dirs))}")
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

    # Confidence per clock name — these functional names are inferences, so
    # mark how strongly each is held rather than presenting them as fact.
    nn = schema.net_names
    conf_by_net = dict(conn.execute(
        select(nn.c.net, nn.c.confidence).where(nn.c.bitstream == bs_id)).fetchall())
    _CONF = {"confirmed": "confirmed", "inferred": "inferred",
             "speculative": "SPEC", "estimate": "est", "guess": "guess"}

    lines = [
        "",
        "── Clock Architecture ──────────────────────────────────",
        "  Names are INFERENCES (spatial/freq heuristics), not verified — see Conf.",
        f"  {'Rank':<5}  {'Net':<8}  {'Name':<20}  {'FFs':>5}  {'Conf':<10}  {'Xing':>4}",
    ]
    for rank, (clk_net, n_ffs) in enumerate(domains):
        name = net_names.get(clk_net, "(unnamed)")
        conf = _CONF.get(conf_by_net.get(clk_net, ""), "auto")
        xing = crossings_in.get(clk_net, 0) + crossings_out.get(clk_net, 0)
        lines.append(
            f"  {rank:<5}  {clk_net:<8}  {name:<20}  {n_ffs:>5}  {conf:<10}  {xing:>4}"
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
        # net is a synthetic boundary net (pad_XX). The real fabric net is one
        # hop back in net_fanout: net_fanout.out_net = pad_XX → .net = fabric_net.
        # Pick the A-side port (primary data, not DDR second phase).
        fabric_net_row = conn.execute(
            select(nf.c.net)
            .where(and_(nf.c.bitstream == bs_id, nf.c.out_net == net,
                        nf.c.pin.like("A%")))
            .limit(1)
        ).fetchone()
        lookup_net = fabric_net_row[0] if fabric_net_row else net

        # Find what drives lookup_net (FF or LUT)
        ff_row = conn.execute(
            select(ffs.c.cell, ffs.c.clk)
            .where(and_(ffs.c.bitstream == bs_id, ffs.c.q == lookup_net))
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
                .where(and_(luts.c.bitstream == bs_id, luts.c.z == lookup_net))
            ).fetchone()
            if lut_row:
                driver_str = f"lut={lut_row[0]}  fn={lut_row[1]}"
            elif fabric_net_row and lookup_net != net:
                # fabric net exists but no fabric cell drives it: clock spine / hard IP
                driver_str = f"spine={net_with_name(lookup_net, net_names)}"
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
    """Categorise the non-reset FFs by functional group.

    A per-FF dump of ~1000 registers is noise at report level.  Group the
    active FFs by the functional prefix of their Q-net name (adc/awg/spi/ebr/
    dac/reg…) so the register makeup is one glance.  Per-FF detail lives in the
    DB (ffs / ff_d_functions) for anyone who needs to drill in.
    """
    import collections, re
    ffs = schema.ffs

    active = conn.execute(
        select(ffs.c.cell, ffs.c.q)
        .where(and_(ffs.c.bitstream == bs_id, ffs.c.d != "1'b0"))
    ).fetchall()

    def _grp(cell, q):
        name = net_names.get(q) if q else None
        if not name:
            return "(unnamed)"
        base = name[5:] if name.startswith("spec_") else name  # strip spec_ marker
        tok = base.split("_")[0]
        # a bare tile/coord token isn't a functional group
        return "(unnamed)" if re.fullmatch(r"r\d+c\d+|ff|n\d+", tok) else tok

    groups = collections.Counter(_grp(cell, q) for cell, q in active)

    lines = [
        "",
        f"── Active Flip-Flops ({len(active)}) ───────────────────────────",
        "  Registers with real D inputs, by functional group (Q-net name):",
    ]
    if not active:
        lines.append("  (none — all FFs stuck at reset)")
        return lines
    for grp, cnt in groups.most_common():
        bar = "█" * min(40, cnt // 5)
        lines.append(f"    {grp:<14} {cnt:>4}  {bar}")
    lines.append("  (per-domain counts: see Clock Architecture; per-FF detail: query ffs.)")
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
            section_config_summary(conn, bs_id, net_names),
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
