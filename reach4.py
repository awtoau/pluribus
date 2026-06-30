#!/usr/bin/env python3
"""Pluribus — auto-naming pass (stage 4).

Runs after reach3.py. Populates net_names and cell_names with mechanically-
derived names for anything not already annotated. Never overwrites an existing
row — every insert uses ON CONFLICT DO NOTHING.

Nine naming passes, in priority order:

  Pass 1  Const nets        — GND / VCC (or GND_n{net} for duplicates)
  Pass 2  Clock nets        — clk_0, clk_1, ... ranked by FF-domain size desc
  Pass 3  FF spatial        — reg_r{R}c{C}[{bit}] for every (row,col) tile group
  Pass 4  Ghost D-inputs    — ghost_d_{index} for floating D-input nets
  Pass 5  Clock semantics   — clk_main / clk_output_reg / clk_src_* / clk_dac_*
  Pass 6  EBR bus grouping  — ebr_main_{role}[{bit}] / ebr_solo_{block}_{role}[{bit}]
  Pass 7  Pad propagation   — {pad_lower}_h1 / {pad_lower}_h2 / {pad_lower}_d
  Pass 8  LUT naming        — lut/buf/inv/and/xor/mux_{net_name} from Z net
  Pass 9  CDC synchronisers — sync1/sync2_{src}_{dst} for 2-FF crossing chains

Usage
-----
  python3 fpga/pluribus/reach4.py [--bitstream V07]
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import engine, die, BACKEND
import schema
from sqlalchemy import select, insert, delete, update, func, and_, or_, text


# ---------------------------------------------------------------------------
# Shared insert helpers (SQLAlchemy Core)
# ---------------------------------------------------------------------------

def _net_names_insert():
    """Return an insert statement for net_names with ON CONFLICT DO NOTHING."""
    if BACKEND == "sqlite":
        return insert(schema.net_names).prefix_with("OR IGNORE")
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    return pg_insert(schema.net_names).on_conflict_do_nothing()


def _cell_names_insert():
    """Return an insert statement for cell_names with ON CONFLICT DO NOTHING."""
    if BACKEND == "sqlite":
        return insert(schema.cell_names).prefix_with("OR IGNORE")
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    return pg_insert(schema.cell_names).on_conflict_do_nothing()


def bulk_insert_nets(conn, rows):
    """Bulk-insert net_names rows. No-op on empty list.

    rows: list of dicts with keys: bitstream, net, name, description, confidence, source
    """
    if not rows:
        return
    conn.execute(_net_names_insert(), rows)


def bulk_insert_cells(conn, rows):
    """Bulk-insert cell_names rows. No-op on empty list.

    rows: list of dicts with keys: bitstream, cell, name, description, confidence
    """
    if not rows:
        return
    conn.execute(_cell_names_insert(), rows)


# ---------------------------------------------------------------------------
# Pass 1: Const nets — GND / VCC
# ---------------------------------------------------------------------------

def pass_const_nets(bs_id, conn):
    """
    Name every const net as GND (value='0') or VCC (value='1').

    There are many const nets — far more than one net can ever be "the" GND or
    VCC.  To keep names unique we use:
      - First GND → 'GND', rest → 'GND_n{raw_net_name}'
      - First VCC → 'VCC', rest → 'VCC_n{raw_net_name}'

    The first net alphabetically by raw name gets the bare name.  This keeps the
    naming deterministic across re-runs.

    ON CONFLICT DO NOTHING silently skips nets already in net_names (e.g. ones
    already hand-named or named by a previous reach4 run).

    confidence='confirmed': the value is proven by reach3 const propagation.
    source='auto_const'
    """
    cn = schema.const_nets
    nn = schema.net_names

    # Load all const nets sorted so naming is deterministic (first one gets bare name)
    const_rows = conn.execute(
        select(cn.c.net, cn.c.const_value)
        .where(cn.c.bitstream == bs_id)
        .order_by(cn.c.const_value, cn.c.net)
    ).fetchall()

    # Check which nets already have names so we don't count them toward "first"
    already_named = {row[0] for row in conn.execute(
        select(nn.c.net).where(nn.c.bitstream == bs_id)
    ).fetchall()}

    gnd_seen = False
    vcc_seen = False
    output_rows = []

    for net, const_value in const_rows:
        if net in already_named:
            continue

        if const_value == '0':
            if not gnd_seen:
                name = 'GND'
                gnd_seen = True
            else:
                name = f'GND_n{net}'
            description = 'Constant logic 0'
        else:
            if not vcc_seen:
                name = 'VCC'
                vcc_seen = True
            else:
                name = f'VCC_n{net}'
            description = 'Constant logic 1'

        output_rows.append({
            "bitstream": bs_id,
            "net": net,
            "name": name,
            "description": description,
            "confidence": "confirmed",
            "source": "auto_const",
        })

    bulk_insert_nets(conn, output_rows)
    return len(output_rows)


# ---------------------------------------------------------------------------
# Pass 2: Clock nets — clk_0, clk_1, ... ranked by FF count desc
# ---------------------------------------------------------------------------

def pass_clock_nets(bs_id, conn):
    """
    Name every ghost clock net as clk_0, clk_1, ... in descending FF-domain size.

    Ghost clock nets are nets that appear ONLY on CLK pins in net_fanout (no
    other pin type) and have fanin=0 in net_stats (not driven by any recoverable
    logic).  There are 38 of them in V07.

    Ranking by FF count means clk_0 is the highest-frequency / widest clock
    (most registers), which matches RE intuition.

    We skip any clock net already in net_names (e.g. named from pins_tsv if a
    pad was already identified as a clock source).

    confidence='estimate': we know it's a clock, rank is mechanical, but we
    don't know which physical signal it corresponds to.
    source='auto_clock'
    """
    nn  = schema.net_names
    nf  = schema.net_fanout
    ns  = schema.net_stats

    # Already-named nets — skip them
    already_named = {row[0] for row in conn.execute(
        select(nn.c.net).where(nn.c.bitstream == bs_id)
    ).fetchall()}

    # Ghost clock nets: nets that ONLY appear on CLK pins in net_fanout,
    # have fanin=0 (not driven by recoverable logic), and are not boundary nets.
    # "Only on CLK pins" means every row for this net has pin='CLK'.
    clock_candidates = conn.execute(
        select(nf.c.net, func.count().label("ff_count"))
        .join(ns, and_(ns.c.bitstream == nf.c.bitstream, ns.c.net == nf.c.net))
        .where(
            and_(
                nf.c.bitstream == bs_id,
                ns.c.fanin == 0,
                ns.c.is_boundary == False,
                ns.c.is_const == False,
            )
        )
        .group_by(nf.c.net)
        .having(func.bool_and(nf.c.pin == 'CLK'))
        .order_by(func.count().desc(), nf.c.net)
    ).fetchall()

    output_rows = []
    rank = 0

    for net, ff_count in clock_candidates:
        if net in already_named:
            continue
        name        = f'clk_{rank}'
        description = f'Clock domain: {ff_count} FFs'
        output_rows.append({
            "bitstream": bs_id,
            "net": net,
            "name": name,
            "description": description,
            "confidence": "estimate",
            "source": "auto_clock",
        })
        rank += 1

    bulk_insert_nets(conn, output_rows)
    return len(output_rows)


# ---------------------------------------------------------------------------
# Pass 3: FF spatial register groups — reg_r{R}c{C}[{bit}]
# ---------------------------------------------------------------------------

# Matches FF cell names like ff_r10c1_A0, ff_r3c10_B1, etc.
_FF_CELL_RE = re.compile(r'^ff_r(\d+)c(\d+)_([A-Da-d])([01])$')

_SLICE_INDEX = {'A': 0, 'B': 1, 'C': 2, 'D': 3}


def _parse_ff_cell(cell_name):
    """
    Parse a FF cell name into (row, col, slice_char, bit).

    Returns (row:int, col:int, slice:str, bit:int) or None if no match.
    Cell names follow the convention: ff_r{R}c{C}_{slice}{bit}
    where slice is A-D and bit is 0 or 1.
    """
    m = _FF_CELL_RE.match(cell_name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3).upper(), int(m.group(4))


def _bit_index(slice_char, bit):
    """
    Convert (slice, bit) → flat register bit index 0-7.

    The LCMXO2 tile has 4 slices (A-D) each with 2 flip-flops (bit 0 and 1).
    We map: A0=0, A1=1, B0=2, B1=3, C0=4, C1=5, D0=6, D1=7.
    """
    return _SLICE_INDEX[slice_char] * 2 + bit


def pass_ff_spatial(bs_id, conn):
    """
    Group FFs by their (row, col) tile location and name them as a register.

    Every FF cell name encodes its tile as ff_r{R}c{C}_{slice}{bit}.  Tiles
    with at least 2 FFs are treated as a register group:

      cell name:  reg_r{R}c{C}[{index}]
      Q net name: reg_r{R}c{C}_q[{index}]

    The bit index runs 0-7 (A0=0, A1=1, B0=2, … D1=7), matching slice order.

    If all FFs in a tile share a single clock net, we include the clock name in
    the description to help correlate registers with clocks.  We look up clock
    names from net_names (pass 2 already ran) so we get 'clk_0' etc. rather than
    raw net IDs.

    Single-FF tiles are not named — they're more likely stray logic bits than
    a register.

    confidence='estimate': spatial grouping is highly likely to be correct for
    FPGA designs that pack related register bits into adjacent tiles.
    source='auto_spatial'
    """
    ffs = schema.ffs
    nn  = schema.net_names
    cn  = schema.cell_names

    # Load all FFs: we need cell name, Q net, and clock net
    all_ffs = conn.execute(
        select(ffs.c.cell, ffs.c.q, ffs.c.clk)
        .where(ffs.c.bitstream == bs_id)
    ).fetchall()

    # Already-named nets and cells — skip them
    named_nets = {row[0] for row in conn.execute(
        select(nn.c.net).where(nn.c.bitstream == bs_id)
    ).fetchall()}

    named_cells = {row[0] for row in conn.execute(
        select(cn.c.cell).where(cn.c.bitstream == bs_id)
    ).fetchall()}

    # Clock net → human name from net_names (so descriptions say 'clk_0' not 'n42')
    net_name_map = {row[0]: row[1] for row in conn.execute(
        select(nn.c.net, nn.c.name).where(nn.c.bitstream == bs_id)
    ).fetchall()}

    # Group FFs by (row, col) tile
    tiles = {}   # (row, col) → list of (cell, slice_char, bit_int, q_net, clk_net)
    for cell, q_net, clk_net in all_ffs:
        parsed = _parse_ff_cell(cell)
        if parsed is None:
            continue
        row, col, slice_char, bit = parsed
        key = (row, col)
        tiles.setdefault(key, []).append((cell, slice_char, bit, q_net, clk_net))

    cell_rows = []
    net_rows  = []
    n_groups  = 0
    n_ffs_named = 0

    for (row, col), members in sorted(tiles.items()):
        if len(members) < 2:
            continue   # single-FF tile — not a register group

        n_groups += 1
        reg_base = f'reg_r{row}c{col}'

        # Determine if the group has a single clock (for richer descriptions)
        clk_nets_in_group = {m[4] for m in members if m[4] is not None}
        if len(clk_nets_in_group) == 1:
            clk_raw  = next(iter(clk_nets_in_group))
            clk_label = net_name_map.get(clk_raw, clk_raw)
            clk_suffix = f', clocked by {clk_label}'
        else:
            clk_suffix = ''

        for cell, slice_char, bit, q_net, _clk_net in members:
            idx = _bit_index(slice_char, bit)

            # Name the cell
            if cell not in named_cells:
                cell_rows.append({
                    "bitstream": bs_id,
                    "cell": cell,
                    "name": f'{reg_base}[{idx}]',
                    "description": f'Register bit {idx} at tile r{row}c{col}{clk_suffix}',
                    "confidence": "estimate",
                })
                n_ffs_named += 1

            # Name the Q net
            if q_net and q_net not in named_nets:
                net_rows.append({
                    "bitstream": bs_id,
                    "net": q_net,
                    "name": f'{reg_base}_q[{idx}]',
                    "description": f'Q output of register bit {idx} at tile r{row}c{col}{clk_suffix}',
                    "confidence": "estimate",
                    "source": "auto_spatial",
                })

    bulk_insert_cells(conn, cell_rows)
    bulk_insert_nets(conn, net_rows)
    return n_groups, n_ffs_named


# ---------------------------------------------------------------------------
# Pass 4: Ghost D-input nets — ghost_d_{index}
# ---------------------------------------------------------------------------

def pass_ghost_d_inputs(bs_id, conn):
    """
    Name floating D-input nets as ghost_d_0, ghost_d_1, ...

    These are nets that:
      - Appear as the D input of at least one FF
      - Have fanin=0 in net_stats (not driven by any LUT or FF in the netlist)
      - Are not boundary nets (not connected to a physical pad or EFB port)
      - Are not const nets (not stuck at 0 or 1)
      - Are not already named

    In the V07 bitstream there are 9 such nets.  They are driven by hard IP not
    captured in the Lattice Diamond netlist export: reset/config sequencers, EFB
    outputs that Diamond doesn't wire into the fabric netlist, or other hard-macro
    outputs.  We flag them so analysis tools can identify "this FF's D input is
    controlled by something invisible to us" rather than treating it as zero.

    confidence='guess': we know the net exists and feeds a FF D input, but we
    cannot determine what drives it from the available netlist information.
    source='auto_ghost'
    """
    nn  = schema.net_names
    nf  = schema.net_fanout
    ns  = schema.net_stats

    # Already-named nets — skip them
    already_named = {row[0] for row in conn.execute(
        select(nn.c.net).where(nn.c.bitstream == bs_id)
    ).fetchall()}

    # Ghost D-input nets: appear on pin='D' in net_fanout, have fanin=0,
    # are not boundary, not const, not the literal '1'b0'/'1'b1' tokens.
    ghost_nets = [row[0] for row in conn.execute(
        select(nf.c.net)
        .distinct()
        .join(ns, and_(ns.c.bitstream == nf.c.bitstream, ns.c.net == nf.c.net))
        .where(
            and_(
                nf.c.bitstream == bs_id,
                nf.c.pin == 'D',
                nf.c.cell_type == 'FF',
                ns.c.fanin == 0,
                ns.c.is_boundary == False,
                ns.c.is_const == False,
                nf.c.net.notlike("1'b%"),
            )
        )
        .order_by(nf.c.net)
    ).fetchall()]

    output_rows = []
    index = 0

    for net in ghost_nets:
        if net in already_named:
            continue
        output_rows.append({
            "bitstream": bs_id,
            "net": net,
            "name": f'ghost_d_{index}',
            "description": 'Unresolved D input: fanin=0, likely hard IP',
            "confidence": "guess",
            "source": "auto_ghost",
        })
        index += 1

    bulk_insert_nets(conn, output_rows)
    return len(output_rows)


# ---------------------------------------------------------------------------
# Pass 5: Clock semantic naming — replace clk_N with functional names
# ---------------------------------------------------------------------------

def pass_clock_semantics(bs_id, conn):
    """
    Replace synthetic clk_N names with semantic names where structure reveals function.

    Rules applied in order (first match wins, only for nets with source='auto_clock'):

    1. clk_main    — highest FF count AND highest crossings-out.
    2. clk_output_reg — crossings-in / (crossings-out + 1) > 4 AND crossings-in > 20.
    3. clk_src_{pad} — all Q-net-fanout FFs reach a pad whose label contains CLK within
                       3 hops.  Strip trailing '_clk' from label → clk_{label_lower}.
    4. clk_dac_data_a/b — FFs whose Q nets reach DAC_D* pads.  More reaches → _a.

    This pass uses ON CONFLICT DO UPDATE to overwrite the clk_N names set by pass 2.
    confidence='estimate', source='auto_clock' (kept).
    """
    nn  = schema.net_names
    cd  = schema.clock_domains
    cx  = schema.clock_crossings
    pm  = schema.pad_map
    ffs = schema.ffs
    ns  = schema.net_stats
    rch = schema.reachability

    # Load all auto_clock nets with FF count (from clock_domains) and
    # crossing counts (from clock_crossings).
    cd_sub = (
        select(cd.c.bitstream, cd.c.clk_net, func.count().label("ff_count"))
        .where(cd.c.bitstream == bs_id)
        .group_by(cd.c.bitstream, cd.c.clk_net)
        .subquery()
    )
    cx_out_sub = (
        select(cx.c.bitstream, cx.c.src_clk, func.count().label("n"))
        .where(cx.c.bitstream == bs_id)
        .group_by(cx.c.bitstream, cx.c.src_clk)
        .subquery()
    )
    cx_in_sub = (
        select(cx.c.bitstream, cx.c.dst_clk, func.count().label("n"))
        .where(cx.c.bitstream == bs_id)
        .group_by(cx.c.bitstream, cx.c.dst_clk)
        .subquery()
    )

    clock_rows = conn.execute(
        select(
            nn.c.net,
            nn.c.name,
            func.coalesce(cd_sub.c.ff_count, 0).label("ff_count"),
            func.coalesce(cx_out_sub.c.n, 0).label("crossings_out"),
            func.coalesce(cx_in_sub.c.n, 0).label("crossings_in"),
        )
        .outerjoin(cd_sub, and_(cd_sub.c.bitstream == nn.c.bitstream, cd_sub.c.clk_net == nn.c.net))
        .outerjoin(cx_out_sub, and_(cx_out_sub.c.bitstream == nn.c.bitstream, cx_out_sub.c.src_clk == nn.c.net))
        .outerjoin(cx_in_sub, and_(cx_in_sub.c.bitstream == nn.c.bitstream, cx_in_sub.c.dst_clk == nn.c.net))
        .where(and_(nn.c.bitstream == bs_id, nn.c.source == 'auto_clock'))
    ).fetchall()

    if not clock_rows:
        return 0

    # Build sorted candidates for rule evaluation
    # Rule 1: highest ff_count AND highest crossings_out
    by_ff   = sorted(clock_rows, key=lambda r: (r[2], r[3]), reverse=True)
    by_xout = sorted(clock_rows, key=lambda r: (r[3], r[2]), reverse=True)

    assigned   = {}   # net → new_name
    used_names = set()

    def assign(net, name):
        if net not in assigned and name not in used_names:
            assigned[net] = name
            used_names.add(name)
            return True
        return False

    # Rule 1 — clk_main: top of both ff_count and crossings_out rankings
    if by_ff and by_xout and by_ff[0][0] == by_xout[0][0]:
        assign(by_ff[0][0], 'clk_main')

    # Rule 2 — clk_output_reg: receives from many domains, sends to few
    for net, _name, _ff, xout, xin in clock_rows:
        if net in assigned:
            continue
        ratio = xin / (xout + 1)
        if ratio > 4 and xin > 20:
            assign(net, 'clk_output_reg')
            break   # at most one

    # Rule 3 — clk_src_{pad}: all live Q nets reach a CLK pad within 3 hops
    # Get pads whose label contains CLK
    # Fix for ILIKE (not portable): use func.upper(col).like(func.upper(val))
    clk_pad_rows = conn.execute(
        select(pm.c.net_in, pm.c.label)
        .where(
            and_(
                pm.c.bitstream == bs_id,
                or_(
                    func.upper(pm.c.label).like(func.upper('%CLK%')),
                    func.upper(pm.c.label).like(func.upper('%_CLK')),
                ),
            )
        )
    ).fetchall()
    clk_pads = {row[0]: row[1] for row in clk_pad_rows}  # net_in → label

    for net, _name, _ff, _xout, _xin in clock_rows:
        if net in assigned:
            continue

        # FFs clocked by this net whose Q has nonzero fanout
        q_nets = [row[0] for row in conn.execute(
            select(ffs.c.q)
            .join(ns, and_(ns.c.bitstream == ffs.c.bitstream, ns.c.net == ffs.c.q))
            .where(and_(ffs.c.bitstream == bs_id, ffs.c.clk == net, ns.c.fanout > 0))
        ).fetchall()]
        if not q_nets:
            continue

        # For each Q net, check reachability to a CLK pad within 3 hops
        reached_pad_labels = set()
        for q_net in q_nets:
            dst_nets = [row[0] for row in conn.execute(
                select(rch.c.dst)
                .where(
                    and_(
                        rch.c.bitstream == bs_id,
                        rch.c.src == q_net,
                        rch.c.min_hops <= 3,
                    )
                )
            ).fetchall()]
            for dst_net in dst_nets:
                if dst_net in clk_pads:
                    reached_pad_labels.add(clk_pads[dst_net])

        if len(reached_pad_labels) == 1:
            # All live Q nets converge on a single CLK pad label
            label = next(iter(reached_pad_labels)).lower()
            if label.endswith('_clk'):
                label = label[:-4]  # strip trailing _clk → clk_dac not clk_dac_clk
            semantic = f'clk_{label}'
            assign(net, semantic)

    # Rule 4 — clk_dac_data_a/b: Q nets reach DAC_D* pads
    # Fix for ILIKE (not portable): use func.upper(col).like(func.upper(val))
    dac_data_pad_rows = conn.execute(
        select(pm.c.net_in, pm.c.label)
        .where(
            and_(
                pm.c.bitstream == bs_id,
                func.upper(pm.c.label).like(func.upper('DAC_D%')),
            )
        )
    ).fetchall()
    dac_data_pads = {row[0]: row[1] for row in dac_data_pad_rows}

    dac_candidates = []   # (net, n_reaches)
    for net, _name, _ff, _xout, _xin in clock_rows:
        if net in assigned:
            continue

        q_nets = [row[0] for row in conn.execute(
            select(ffs.c.q)
            .join(ns, and_(ns.c.bitstream == ffs.c.bitstream, ns.c.net == ffs.c.q))
            .where(and_(ffs.c.bitstream == bs_id, ffs.c.clk == net, ns.c.fanout > 0))
        ).fetchall()]

        dac_reach_count = 0
        for q_net in q_nets:
            dst_nets = [row[0] for row in conn.execute(
                select(rch.c.dst)
                .where(
                    and_(
                        rch.c.bitstream == bs_id,
                        rch.c.src == q_net,
                        rch.c.min_hops <= 3,
                    )
                )
            ).fetchall()]
            for dst_net in dst_nets:
                if dst_net in dac_data_pads:
                    dac_reach_count += 1

        if dac_reach_count > 0:
            dac_candidates.append((net, dac_reach_count))

    dac_candidates.sort(key=lambda r: r[1], reverse=True)
    if len(dac_candidates) >= 1:
        assign(dac_candidates[0][0], 'clk_dac_data_a')
    if len(dac_candidates) >= 2:
        assign(dac_candidates[1][0], 'clk_dac_data_b')

    # Write back — overwrite the clk_N names (UPDATE)
    renamed = 0
    for net, new_name in assigned.items():
        result = conn.execute(
            update(nn)
            .where(
                and_(
                    nn.c.bitstream == bs_id,
                    nn.c.net == net,
                    nn.c.source == 'auto_clock',
                )
            )
            .values(name=new_name)
        )
        if result.rowcount:
            renamed += 1

    return renamed


# ---------------------------------------------------------------------------
# Pass 6: EBR bus grouping and net naming
# ---------------------------------------------------------------------------

def pass_ebr_bus(bs_id, conn):
    """
    Find groups of EBR blocks sharing address/data nets and name them.

    Nets appearing as JA/JB/JC/JD ports across >= 3 EBR blocks form the "main
    EBR group".  Their nets are named ebr_main_{bus_role}[{bit_index}].

    EBR blocks not in the main group get solo names:
    ebr_solo_{block}_{bus_role}[{bit_index}].

    Looks up bus_role and bit_index from the ebr_buses table (written by
    the EBR analysis step).

    confidence='estimate', source='auto_ebr'.
    """
    ep  = schema.ebr_ports
    eb  = schema.ebr_buses

    # Find nets shared by >= 3 EBR blocks on J[ABCD] ports.
    # Use text() for the regex/substring since SQLAlchemy doesn't have a
    # portable substring/regex extract across SQLite and PostgreSQL.
    if BACKEND == "postgres":
        main_group_sql = text("""
            SELECT net
            FROM (
                SELECT substring(port, 2, 1) AS port_letter, net, block
                FROM ebr_ports
                WHERE bitstream = :bs_id AND net IS NOT NULL
                  AND port ~ '^J[ABCD]\\d+$'
            ) t
            GROUP BY port_letter, net
            HAVING count(distinct block) >= 3
        """)
    else:
        # SQLite: use glob pattern and substr
        main_group_sql = text("""
            SELECT net
            FROM (
                SELECT substr(port, 2, 1) AS port_letter, net, block
                FROM ebr_ports
                WHERE bitstream = :bs_id AND net IS NOT NULL
                  AND port GLOB 'J[ABCD]*'
            ) t
            GROUP BY port_letter, net
            HAVING count(distinct block) >= 3
        """)
    main_group_nets = {row[0] for row in conn.execute(main_group_sql, {"bs_id": bs_id}).fetchall()}

    # All EBR ports with their bus metadata
    all_ebr_ports = conn.execute(
        select(ep.c.block, ep.c.port, ep.c.net, eb.c.bus_role, eb.c.bit_index)
        .join(eb, and_(
            eb.c.bitstream == ep.c.bitstream,
            eb.c.block == ep.c.block,
            eb.c.port == ep.c.port,
        ))
        .where(and_(ep.c.bitstream == bs_id, ep.c.net.isnot(None)))
    ).fetchall()

    net_rows = []
    main_count = 0
    solo_count = 0

    for block, _port, net, bus_role, bit_index in all_ebr_ports:
        if bus_role is None or bit_index is None:
            continue
        if net in main_group_nets:
            name = f'ebr_main_{bus_role}[{bit_index}]'
            desc = f'EBR main group {bus_role} bit {bit_index}'
            main_count += 1
        else:
            # Sanitise block name: "R6C20" → "r6c20"
            block_safe = re.sub(r'[^A-Za-z0-9]', '_', block).lower()
            name = f'ebr_solo_{block_safe}_{bus_role}[{bit_index}]'
            desc = f'EBR block {block} {bus_role} bit {bit_index}'
            solo_count += 1

        net_rows.append({
            "bitstream": bs_id,
            "net": net,
            "name": name,
            "description": desc,
            "confidence": "estimate",
            "source": "auto_ebr",
        })

    bulk_insert_nets(conn, net_rows)
    return len(net_rows), main_count, solo_count


# ---------------------------------------------------------------------------
# Pass 7: Named pad net propagation
# ---------------------------------------------------------------------------

def pass_pad_propagation(bs_id, conn):
    """
    Propagate names outward from named pads into nearby fabric nets and cells.

    For input pads: name hop-1 and hop-2 reachable nets (skipping clock nets).
    Hop-2 names are only given if the net is uniquely reached from this pad
    (not also reachable from another named pad at hop <= 1).

    For output pads: name the driving FF's D net and the FF cell itself.

    confidence='estimate', source='auto_propagate'.
    """
    pm  = schema.pad_map
    nn  = schema.net_names
    cn  = schema.cell_names
    ns  = schema.net_stats
    rch = schema.reachability
    nf  = schema.net_fanout
    ffs = schema.ffs

    # Load all named pads (input and output)
    pads = conn.execute(
        select(pm.c.net_in, pm.c.net_out, pm.c.label, pm.c.direction)
        .where(pm.c.bitstream == bs_id)
    ).fetchall()

    # Already-named nets and cells
    named_nets = {row[0] for row in conn.execute(
        select(nn.c.net).where(nn.c.bitstream == bs_id)
    ).fetchall()}

    named_cells = {row[0] for row in conn.execute(
        select(cn.c.cell).where(cn.c.bitstream == bs_id)
    ).fetchall()}

    # Clock nets — skip these during hop propagation
    clock_nets = {row[0] for row in conn.execute(
        select(ns.c.net).where(and_(ns.c.bitstream == bs_id, ns.c.is_clock == True))
    ).fetchall()}

    # For hop-2 uniqueness: build map net → set of named-pad net_ins that reach
    # it within 1 hop (so we can check if a hop-2 net is already reachable at
    # hop 1 from another pad).
    hop1_rows = conn.execute(
        select(rch.c.src, rch.c.dst)
        .join(pm, and_(pm.c.bitstream == rch.c.bitstream, pm.c.net_in == rch.c.src))
        .join(nn, and_(nn.c.bitstream == pm.c.bitstream, nn.c.net == pm.c.net_in))
        .where(and_(rch.c.bitstream == bs_id, rch.c.min_hops == 1))
    ).fetchall()
    hop1_from_named_pad = {}   # dst_net → set of src pad net_ins
    for src, dst in hop1_rows:
        hop1_from_named_pad.setdefault(dst, set()).add(src)

    net_rows  = []
    cell_rows = []
    added_nets = set()

    def add_net(net, name, desc):
        if net and net not in named_nets and net not in added_nets and net not in clock_nets:
            net_rows.append({
                "bitstream": bs_id,
                "net": net,
                "name": name,
                "description": desc,
                "confidence": "estimate",
                "source": "auto_propagate",
            })
            added_nets.add(net)

    def add_cell(cell, name, desc):
        if cell and cell not in named_cells:
            cell_rows.append({
                "bitstream": bs_id,
                "cell": cell,
                "name": name,
                "description": desc,
                "confidence": "estimate",
            })

    for net_in, net_out, label, direction in pads:
        pad_lower = label.lower()

        # Only propagate from pads that have a name in net_names
        if net_in and net_in not in named_nets:
            continue

        if direction in ('input', 'inout', None) and net_in:
            # Fetch hops 1 and 2 from this pad's net_in
            reach_rows = conn.execute(
                select(rch.c.dst, rch.c.min_hops)
                .where(
                    and_(
                        rch.c.bitstream == bs_id,
                        rch.c.src == net_in,
                        rch.c.min_hops <= 2,
                    )
                )
            ).fetchall()
            for dst_net, hops in reach_rows:
                if dst_net in clock_nets:
                    continue
                if hops == 1:
                    add_net(dst_net, f'{pad_lower}_h1',
                            f'1 hop from {label} pad')
                elif hops == 2:
                    # Only name if not already reachable at hop-1 from another named pad
                    other_pads_at_1 = hop1_from_named_pad.get(dst_net, set())
                    other_pads_at_1 = other_pads_at_1 - {net_in}
                    if not other_pads_at_1:
                        add_net(dst_net, f'{pad_lower}_h2',
                                f'2 hops from {label} pad')

        if direction in ('output', 'inout') and net_out:
            # Find FF driving net_out (FF whose Q = net_out)
            ff_rows = conn.execute(
                select(nf.c.cell, ffs.c.d)
                .join(ffs, and_(ffs.c.bitstream == nf.c.bitstream, ffs.c.cell == nf.c.cell))
                .where(
                    and_(
                        nf.c.bitstream == bs_id,
                        nf.c.out_net == net_out,
                        nf.c.cell_type == 'FF',
                    )
                )
            ).fetchall()
            for ff_cell, d_net in ff_rows:
                add_net(d_net, f'{pad_lower}_d',
                        f'D input of output FF driving {label}')
                add_cell(ff_cell, f'ff_{pad_lower}',
                         f'Output FF driving {label} pad')

    bulk_insert_nets(conn, net_rows)
    bulk_insert_cells(conn, cell_rows)
    return len(net_rows) + len(cell_rows)


# ---------------------------------------------------------------------------
# Pass 8: LUT naming from output net
# ---------------------------------------------------------------------------

# Map fn-prefix → cell-name prefix
_LUT_FN_PREFIXES = [
    ('BUF(', 'buf'),
    ('INV(', 'inv'),
    ('AND(', 'and'),
    ('XOR(', 'xor'),
    ('MUX(', 'mux'),
]


def pass_lut_naming(bs_id, conn):
    """
    Name LUT cells from their Z (output) net name.

    For every LUT whose output net is already in net_names, derive a cell name
    by combining a fn-based prefix with the net name:

      BUF → buf_{net_name}, INV → inv_{net_name}, AND → and_{net_name},
      XOR → xor_{net_name}, MUX → mux_{net_name}, else → lut_{net_name}

    confidence='estimate', source='auto_lut'.
    """
    nn   = schema.net_names
    cn   = schema.cell_names
    luts = schema.luts

    # Load named nets
    net_name_map = {row[0]: row[1] for row in conn.execute(
        select(nn.c.net, nn.c.name).where(nn.c.bitstream == bs_id)
    ).fetchall()}

    # Already-named cells
    named_cells = {row[0] for row in conn.execute(
        select(cn.c.cell).where(cn.c.bitstream == bs_id)
    ).fetchall()}

    # Load all LUT cells with their Z net and fn (schema column is 'z')
    all_luts = conn.execute(
        select(luts.c.cell, luts.c.z, luts.c.fn)
        .where(luts.c.bitstream == bs_id)
    ).fetchall()

    cell_rows = []

    for cell, z_net, fn in all_luts:
        if cell in named_cells:
            continue
        if z_net not in net_name_map:
            continue

        net_name = net_name_map[z_net]
        fn_str   = fn or ''

        prefix = 'lut'
        for fn_pfx, cell_pfx in _LUT_FN_PREFIXES:
            if fn_str.startswith(fn_pfx):
                prefix = cell_pfx
                break

        cell_rows.append({
            "bitstream": bs_id,
            "cell": cell,
            "name": f'{prefix}_{net_name}',
            "description": f'LUT driving {net_name}',
            "confidence": "estimate",
        })

    bulk_insert_cells(conn, cell_rows)
    return len(cell_rows)


# ---------------------------------------------------------------------------
# Pass 9: CDC synchroniser detection
# ---------------------------------------------------------------------------

def pass_cdc_synchronisers(bs_id, conn):
    """
    Detect the classic 2-FF synchroniser pattern.

    Pattern:
      FF_A (src domain) → Q_A → FF_B.D  (no intervening LUT)
      FF_B.clk ≠ FF_A.clk  (cross-domain)
      FF_B.ce = '1''b1'    (always enabled)
      FF_B.Q → (directly or via 1 LUT) → FF_C.D
      FF_C.clk = FF_B.clk  (both in destination domain)

    FF_B is the stage-1 synchroniser (capture FF), FF_C is stage-2 (re-clock).

    Results are written to cdc_synchronisers and stage1/stage2 FF cells are
    named sync1/sync2_{src_clk}_{dst_clk}.

    confidence='estimate', source='auto_cdc'.
    """
    schema.init()   # ensure cdc_synchronisers exists
    nn   = schema.net_names
    cn   = schema.cell_names
    ffs  = schema.ffs
    luts = schema.luts
    cdc  = schema.cdc_synchronisers

    # Load net names for clock labelling
    net_name_map = {row[0]: row[1] for row in conn.execute(
        select(nn.c.net, nn.c.name).where(nn.c.bitstream == bs_id)
    ).fetchall()}

    def clk_label(clk_net):
        """Return semantic name if available, else strip leading 'n' from raw id."""
        nm = net_name_map.get(clk_net)
        if nm:
            return nm
        s = str(clk_net)
        return s.lstrip('n') if s.startswith('n') else s

    # Load all FFs: cell, q, d, clk, ce
    all_ffs = conn.execute(
        select(ffs.c.cell, ffs.c.q, ffs.c.d, ffs.c.clk, ffs.c.ce)
        .where(ffs.c.bitstream == bs_id)
    ).fetchall()

    # Index: q_net → FF info (one FF per Q net)
    ff_by_q   = {}   # q_net → (cell, d, clk, ce)
    # Index: d_net → list of FFs whose D = this net
    ff_by_d   = {}   # d_net → list of (cell, q, clk, ce)
    ff_by_cell = {}  # cell  → (q, d, clk, ce)

    for cell, q, d, clk, ce in all_ffs:
        if q:
            ff_by_q[q] = (cell, d, clk, ce)
        if d:
            ff_by_d.setdefault(d, []).append((cell, q, clk, ce))
        ff_by_cell[cell] = (q, d, clk, ce)

    # LUT index: z → list of (cell, inputs)  — for 1-LUT hop check
    # (schema column is 'z', not 'z_net')
    all_luts_z = conn.execute(
        select(luts.c.cell, luts.c.z)
        .where(luts.c.bitstream == bs_id)
    ).fetchall()
    lut_by_output = {}  # z_net → cell
    for lut_cell, z_net in all_luts_z:
        lut_by_output[z_net] = lut_cell

    # Build lut z → input nets for 1-LUT hop via LUT (using luts columns a/b/c/d)
    all_luts_inputs = conn.execute(
        select(luts.c.cell, luts.c.a, luts.c.b, luts.c.c, luts.c.d)
        .where(luts.c.bitstream == bs_id)
    ).fetchall()
    lut_inputs = {}  # lut_cell → list of input nets
    for lut_cell, a, b, c, dd in all_luts_inputs:
        lut_inputs[lut_cell] = [n for n in (a, b, c, dd) if n is not None]

    always_enabled = {"1'b1", "1b1", "VCC", "vcc", None}

    synchronisers = []   # (src_ff, src_clk, stage1_ff, stage2_ff, dst_clk)
    seen_stage1  = set()

    for ff_a_cell, q_a, d_a, clk_a, ce_a in all_ffs:
        if not q_a or not clk_a:
            continue

        # Find FF_B whose D = Q_A (direct connection, no LUT)
        candidates_b = ff_by_d.get(q_a, [])
        for ff_b_cell, q_b, clk_b, ce_b in candidates_b:
            if not clk_b or clk_b == clk_a:
                continue   # must be cross-domain
            if ce_b not in always_enabled:
                continue   # must be always enabled

            if ff_b_cell in seen_stage1:
                continue

            # Find FF_C in same domain as FF_B whose D = Q_B directly or via 1 LUT
            if not q_b:
                continue

            ff_c_found = None

            # Direct: FF_C.D = Q_B
            for ff_c_cell, _, clk_c, _ce_c in ff_by_d.get(q_b, []):
                if clk_c == clk_b:
                    ff_c_found = ff_c_cell
                    break

            # Via 1 LUT: q_b is Q of FF_B; a single intervening LUT would have
            # q_b as one of its inputs and its Z net feeds FF_C.D.
            if ff_c_found is None:
                for lut_z, lut_cell in lut_by_output.items():
                    if q_b in lut_inputs.get(lut_cell, []):
                        for ff_c_cell, _, clk_c, _ce_c in ff_by_d.get(lut_z, []):
                            if clk_c == clk_b:
                                ff_c_found = ff_c_cell
                                break
                    if ff_c_found:
                        break

            if ff_c_found is None:
                continue

            seen_stage1.add(ff_b_cell)
            synchronisers.append((ff_a_cell, clk_a, ff_b_cell, ff_c_found, clk_b))

    # Insert into cdc_synchronisers
    if synchronisers:
        cdc_rows = [
            {
                "bitstream": bs_id,
                "src_ff": src_ff,
                "src_clk": src_clk,
                "stage1_ff": stage1_ff,
                "stage2_ff": stage2_ff,
                "dst_clk": dst_clk,
            }
            for src_ff, src_clk, stage1_ff, stage2_ff, dst_clk in synchronisers
        ]
        if BACKEND == "sqlite":
            cdc_stmt = insert(cdc).prefix_with("OR IGNORE")
        else:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            cdc_stmt = pg_insert(cdc).on_conflict_do_nothing()
        conn.execute(cdc_stmt, cdc_rows)

    # Name stage1 and stage2 FF cells
    named_cells_cur = {row[0] for row in conn.execute(
        select(cn.c.cell).where(cn.c.bitstream == bs_id)
    ).fetchall()}

    cell_rows = []
    for src_ff, src_clk, stage1_ff, stage2_ff, dst_clk in synchronisers:
        src_label = clk_label(src_clk)
        dst_label = clk_label(dst_clk)

        name1 = f'sync1_{src_label}_{dst_label}'
        name2 = f'sync2_{src_label}_{dst_label}'

        if stage1_ff not in named_cells_cur:
            cell_rows.append({
                "bitstream": bs_id,
                "cell": stage1_ff,
                "name": name1,
                "description": f'CDC sync stage 1: {src_label} → {dst_label}',
                "confidence": "estimate",
            })
        if stage2_ff not in named_cells_cur:
            cell_rows.append({
                "bitstream": bs_id,
                "cell": stage2_ff,
                "name": name2,
                "description": f'CDC sync stage 2: {src_label} → {dst_label}',
                "confidence": "estimate",
            })

    bulk_insert_cells(conn, cell_rows)
    return len(synchronisers)


# ---------------------------------------------------------------------------
# Main — run all nine passes in order
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--bitstream", default="V07",
        help="Bitstream label to annotate (default: V07)",
    )
    args = ap.parse_args()

    # Resolve bitstream ID
    bs = schema.bitstreams
    with engine().connect() as conn:
        row = conn.execute(
            select(bs.c.id).where(bs.c.label == args.bitstream)
        ).fetchone()
        if not row:
            die(f"Bitstream {args.bitstream!r} not found — run load.py first")
        bs_id = row[0]

    wall_start = time.time()
    timings    = []

    def run_pass(label, fn):
        """Open a fresh connection, run fn(conn), close, record timing."""
        print(f"{label}…", flush=True)
        t = time.time()
        with engine().begin() as conn:
            result = fn(conn)
        elapsed = time.time() - t
        timings.append((label, elapsed))
        return result, elapsed

    # Pass 1 — const net naming
    n, elapsed = run_pass(
        "Pass 1: const net naming (GND / VCC)",
        lambda c: pass_const_nets(bs_id, c),
    )
    print(f"  Named {n} const nets  ({elapsed:.2f}s)")

    # Pass 2 — clock net naming (must run before pass 3 so clock names are available)
    n, elapsed = run_pass(
        "Pass 2: clock net naming (clk_0, clk_1, …)",
        lambda c: pass_clock_nets(bs_id, c),
    )
    print(f"  Named {n} clock nets  ({elapsed:.2f}s)")

    # Pass 3 — FF spatial register groups
    result, elapsed = run_pass(
        "Pass 3: FF spatial register groups",
        lambda c: pass_ff_spatial(bs_id, c),
    )
    n_groups, n_ffs = result
    print(f"  Named {n_groups} register groups ({n_ffs} FFs)  ({elapsed:.2f}s)")

    # Pass 4 — ghost D-input nets
    n, elapsed = run_pass(
        "Pass 4: ghost D-input nets",
        lambda c: pass_ghost_d_inputs(bs_id, c),
    )
    print(f"  Named {n} ghost D-input nets  ({elapsed:.2f}s)")

    # Pass 5 — clock semantic naming
    n, elapsed = run_pass(
        "Pass 5: clock semantic naming",
        lambda c: pass_clock_semantics(bs_id, c),
    )
    print(f"  Renamed {n} clock nets with semantic names  ({elapsed:.2f}s)")

    # Pass 6 — EBR bus grouping
    result, elapsed = run_pass(
        "Pass 6: EBR bus grouping",
        lambda c: pass_ebr_bus(bs_id, c),
    )
    n_ebr, n_main, n_solo = result
    print(f"  Named {n_ebr} EBR bus nets ({n_main} main group, {n_solo} solo)  ({elapsed:.2f}s)")

    # Pass 7 — named pad net propagation
    n, elapsed = run_pass(
        "Pass 7: named pad net propagation",
        lambda c: pass_pad_propagation(bs_id, c),
    )
    print(f"  Named {n} nets from pad propagation  ({elapsed:.2f}s)")

    # Pass 8 — LUT naming from output net
    n, elapsed = run_pass(
        "Pass 8: LUT naming from output net",
        lambda c: pass_lut_naming(bs_id, c),
    )
    print(f"  Named {n} LUT cells from output net names  ({elapsed:.2f}s)")

    # Pass 9 — CDC synchroniser detection
    n, elapsed = run_pass(
        "Pass 9: CDC synchroniser detection",
        lambda c: pass_cdc_synchronisers(bs_id, c),
    )
    print(f"  Detected {n} CDC synchroniser pairs  ({elapsed:.2f}s)")

    # Summary
    total_elapsed = time.time() - wall_start
    print(f"\n══ reach4 complete  ({total_elapsed:.2f}s) ══")
    print("  Stage timings:")
    for pass_name, t_pass in timings:
        bar = "█" * max(1, round(t_pass / total_elapsed * 30))
        print(f"  {pass_name:<48}  {t_pass:5.2f}s  {bar}")

    # Quick coverage summary
    with engine().connect() as conn:
        nt  = schema.nets
        nn  = schema.net_names
        ffs = schema.ffs
        cn  = schema.cell_names
        lu  = schema.luts

        total_nets  = conn.execute(select(func.count()).select_from(nt).where(nt.c.bitstream == bs_id)).scalar()
        named_nets  = conn.execute(select(func.count()).select_from(nn).where(nn.c.bitstream == bs_id)).scalar()
        total_ffs   = conn.execute(select(func.count()).select_from(ffs).where(ffs.c.bitstream == bs_id)).scalar()
        named_cells = conn.execute(select(func.count()).select_from(cn).where(cn.c.bitstream == bs_id)).scalar()
        total_luts  = conn.execute(select(func.count()).select_from(lu).where(lu.c.bitstream == bs_id)).scalar()
        named_luts  = conn.execute(
            select(func.count())
            .select_from(cn.join(lu, and_(lu.c.bitstream == cn.c.bitstream, lu.c.cell == cn.c.cell)))
            .where(cn.c.bitstream == bs_id)
        ).scalar()

    net_pct  = 100.0 * named_nets  / total_nets  if total_nets  else 0
    cell_pct = 100.0 * named_cells / total_ffs   if total_ffs   else 0
    lut_pct  = 100.0 * named_luts  / total_luts  if total_luts  else 0
    print(f"\n  Coverage: {named_nets}/{total_nets} nets named ({net_pct:.1f}%),",
          f"{named_cells}/{total_ffs} FF cells named ({cell_pct:.1f}%),",
          f"{named_luts}/{total_luts} LUT cells named ({lut_pct:.1f}%)")


if __name__ == "__main__":
    main()
