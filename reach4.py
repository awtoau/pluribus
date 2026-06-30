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

import psycopg2.extras

sys.path.insert(0, str(Path(__file__).parent))
from db import connect, die


# ---------------------------------------------------------------------------
# Shared insert helper (same as reach3.py)
# ---------------------------------------------------------------------------

def bulk_insert(cursor, sql, rows):
    """Run psycopg2 execute_values for a batch of rows. No-op on empty list."""
    if rows:
        psycopg2.extras.execute_values(cursor, sql, rows, page_size=2000)


# ---------------------------------------------------------------------------
# Pass 1: Const nets — GND / VCC
# ---------------------------------------------------------------------------

_NET_NAME_INSERT = """
    INSERT INTO net_names (bitstream, net, name, description, confidence, source)
    VALUES %s
    ON CONFLICT (bitstream, net) DO NOTHING
"""

_CELL_NAME_INSERT = """
    INSERT INTO cell_names (bitstream, cell, name, description, confidence)
    VALUES %s
    ON CONFLICT (bitstream, cell) DO NOTHING
"""


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
    cur = conn.cursor()

    # Load all const nets sorted so naming is deterministic (first one gets bare name)
    cur.execute("""
        SELECT net, const_value
        FROM const_nets
        WHERE bitstream = %s
        ORDER BY const_value, net
    """, (bs_id,))
    const_rows = cur.fetchall()

    # Check which nets already have names so we don't count them toward "first"
    cur.execute("SELECT net FROM net_names WHERE bitstream = %s", (bs_id,))
    already_named = {row[0] for row in cur.fetchall()}

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

        output_rows.append((bs_id, net, name, description, 'confirmed', 'auto_const'))

    bulk_insert(cur, _NET_NAME_INSERT, output_rows)
    conn.commit()
    cur.close()
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
    cur = conn.cursor()

    # Already-named nets — skip them
    cur.execute("SELECT net FROM net_names WHERE bitstream = %s", (bs_id,))
    already_named = {row[0] for row in cur.fetchall()}

    # Ghost clock nets: nets that ONLY appear on CLK pins in net_fanout,
    # have fanin=0 (not driven by recoverable logic), and are not boundary nets.
    # "Only on CLK pins" means every row for this net has pin='CLK'.
    cur.execute("""
        SELECT
            nf.net,
            count(*) AS ff_count
        FROM net_fanout nf
        JOIN net_stats ns
          ON ns.bitstream = nf.bitstream
         AND ns.net       = nf.net
        WHERE nf.bitstream = %s
          AND ns.fanin     = 0
          AND ns.is_boundary = FALSE
          AND ns.is_const    = FALSE
        GROUP BY nf.net
        HAVING bool_and(nf.pin = 'CLK')
        ORDER BY ff_count DESC, nf.net
    """, (bs_id,))
    clock_candidates = cur.fetchall()

    output_rows = []
    rank = 0

    for net, ff_count in clock_candidates:
        if net in already_named:
            continue
        name        = f'clk_{rank}'
        description = f'Clock domain: {ff_count} FFs'
        output_rows.append((bs_id, net, name, description, 'estimate', 'auto_clock'))
        rank += 1

    bulk_insert(cur, _NET_NAME_INSERT, output_rows)
    conn.commit()
    cur.close()
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
    cur = conn.cursor()

    # Load all FFs: we need cell name, Q net, and clock net
    cur.execute("""
        SELECT cell, q, clk
        FROM ffs
        WHERE bitstream = %s
    """, (bs_id,))
    all_ffs = cur.fetchall()

    # Already-named nets and cells — skip them
    cur.execute("SELECT net  FROM net_names  WHERE bitstream = %s", (bs_id,))
    named_nets = {row[0] for row in cur.fetchall()}

    cur.execute("SELECT cell FROM cell_names WHERE bitstream = %s", (bs_id,))
    named_cells = {row[0] for row in cur.fetchall()}

    # Clock net → human name from net_names (so descriptions say 'clk_0' not 'n42')
    cur.execute("SELECT net, name FROM net_names WHERE bitstream = %s", (bs_id,))
    net_name_map = {net: name for net, name in cur.fetchall()}

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
                cell_rows.append((
                    bs_id,
                    cell,
                    f'{reg_base}[{idx}]',
                    f'Register bit {idx} at tile r{row}c{col}{clk_suffix}',
                    'estimate',
                ))
                n_ffs_named += 1

            # Name the Q net
            if q_net and q_net not in named_nets:
                net_rows.append((
                    bs_id,
                    q_net,
                    f'{reg_base}_q[{idx}]',
                    f'Q output of register bit {idx} at tile r{row}c{col}{clk_suffix}',
                    'estimate',
                    'auto_spatial',
                ))

    bulk_insert(cur, _CELL_NAME_INSERT, cell_rows)
    bulk_insert(cur, _NET_NAME_INSERT,  net_rows)
    conn.commit()
    cur.close()
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
    cur = conn.cursor()

    # Already-named nets — skip them
    cur.execute("SELECT net FROM net_names WHERE bitstream = %s", (bs_id,))
    already_named = {row[0] for row in cur.fetchall()}

    # Ghost D-input nets: appear on pin='D' in net_fanout, have fanin=0,
    # are not boundary, not const, not the literal '1'b0'/'1'b1' tokens.
    cur.execute("""
        SELECT DISTINCT nf.net
        FROM net_fanout nf
        JOIN net_stats ns
          ON ns.bitstream = nf.bitstream
         AND ns.net       = nf.net
        WHERE nf.bitstream  = %s
          AND nf.pin        = 'D'
          AND nf.cell_type  = 'FF'
          AND ns.fanin      = 0
          AND ns.is_boundary = FALSE
          AND ns.is_const    = FALSE
          AND nf.net NOT LIKE '1''b%%'
        ORDER BY nf.net
    """, (bs_id,))
    ghost_nets = [row[0] for row in cur.fetchall()]

    output_rows = []
    index = 0

    for net in ghost_nets:
        if net in already_named:
            continue
        output_rows.append((
            bs_id,
            net,
            f'ghost_d_{index}',
            'Unresolved D input: fanin=0, likely hard IP',
            'guess',
            'auto_ghost',
        ))
        index += 1

    bulk_insert(cur, _NET_NAME_INSERT, output_rows)
    conn.commit()
    cur.close()
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
    cur = conn.cursor()

    # Load all auto_clock nets with FF count (from clock_domains) and
    # crossing counts (from clock_crossings).
    cur.execute("""
        SELECT
            nn.net,
            nn.name,
            COALESCE(cd.ff_count,  0) AS ff_count,
            COALESCE(cx_out.n, 0) AS crossings_out,
            COALESCE(cx_in.n,  0) AS crossings_in
        FROM net_names nn
        LEFT JOIN (
            SELECT bitstream, clk_net, count(*) AS ff_count
            FROM clock_domains
            WHERE bitstream = %s
            GROUP BY bitstream, clk_net
        ) cd ON cd.bitstream = nn.bitstream AND cd.clk_net = nn.net
        LEFT JOIN (
            SELECT bitstream, src_clk, count(*) AS n
            FROM clock_crossings
            WHERE bitstream = %s
            GROUP BY bitstream, src_clk
        ) cx_out ON cx_out.bitstream = nn.bitstream AND cx_out.src_clk = nn.net
        LEFT JOIN (
            SELECT bitstream, dst_clk, count(*) AS n
            FROM clock_crossings
            WHERE bitstream = %s
            GROUP BY bitstream, dst_clk
        ) cx_in ON cx_in.bitstream = nn.bitstream AND cx_in.dst_clk = nn.net
        WHERE nn.bitstream = %s
          AND nn.source    = 'auto_clock'
    """, (bs_id, bs_id, bs_id, bs_id))
    clock_rows = cur.fetchall()  # (net, name, ff_count, xout, xin)

    if not clock_rows:
        cur.close()
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
    cur.execute("""
        SELECT pm.net_in, pm.label
        FROM pad_map pm
        WHERE pm.bitstream = %s
          AND (pm.label ILIKE '%%CLK%%' OR pm.label ILIKE '%%_CLK')
    """, (bs_id,))
    clk_pads = {row[0]: row[1] for row in cur.fetchall()}  # net_in → label

    for net, _name, _ff, _xout, _xin in clock_rows:
        if net in assigned:
            continue

        # FFs clocked by this net whose Q has nonzero fanout
        cur.execute("""
            SELECT f.q
            FROM ffs f
            JOIN net_stats ns ON ns.bitstream = f.bitstream AND ns.net = f.q
            WHERE f.bitstream = %s AND f.clk = %s AND ns.fanout > 0
        """, (bs_id, net))
        q_nets = [row[0] for row in cur.fetchall()]
        if not q_nets:
            continue

        # For each Q net, check reachability to a CLK pad within 3 hops
        reached_pad_labels = set()
        for q_net in q_nets:
            cur.execute("""
                SELECT rch.dst
                FROM reachability rch
                WHERE rch.bitstream = %s
                  AND rch.src       = %s
                  AND rch.min_hops  <= 3
            """, (bs_id, q_net))
            for (dst_net,) in cur.fetchall():
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
    cur.execute("""
        SELECT pm.net_in, pm.label
        FROM pad_map pm
        WHERE pm.bitstream = %s AND pm.label ILIKE 'DAC_D%%'
    """, (bs_id,))
    dac_data_pads = {row[0]: row[1] for row in cur.fetchall()}

    dac_candidates = []   # (net, n_reaches)
    for net, _name, _ff, _xout, _xin in clock_rows:
        if net in assigned:
            continue

        cur.execute("""
            SELECT f.q
            FROM ffs f
            JOIN net_stats ns ON ns.bitstream = f.bitstream AND ns.net = f.q
            WHERE f.bitstream = %s AND f.clk = %s AND ns.fanout > 0
        """, (bs_id, net))
        q_nets = [row[0] for row in cur.fetchall()]

        dac_reach_count = 0
        for q_net in q_nets:
            cur.execute("""
                SELECT rch.dst
                FROM reachability rch
                WHERE rch.bitstream = %s AND rch.src = %s
                  AND rch.min_hops <= 3
            """, (bs_id, q_net))
            for (dst_net,) in cur.fetchall():
                if dst_net in dac_data_pads:
                    dac_reach_count += 1

        if dac_reach_count > 0:
            dac_candidates.append((net, dac_reach_count))

    dac_candidates.sort(key=lambda r: r[1], reverse=True)
    if len(dac_candidates) >= 1:
        assign(dac_candidates[0][0], 'clk_dac_data_a')
    if len(dac_candidates) >= 2:
        assign(dac_candidates[1][0], 'clk_dac_data_b')

    # Write back — overwrite the clk_N names (DO UPDATE)
    renamed = 0
    for net, new_name in assigned.items():
        cur.execute("""
            UPDATE net_names
            SET name = %s
            WHERE bitstream = %s AND net = %s AND source = 'auto_clock'
        """, (new_name, bs_id, net))
        if cur.rowcount:
            renamed += 1

    conn.commit()
    cur.close()
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
    cur = conn.cursor()

    # Find nets shared by >= 3 EBR blocks on J[ABCD] ports
    cur.execute("""
        SELECT port_letter, net, count(distinct block) AS n_blocks
        FROM (
            SELECT substring(port, 2, 1) AS port_letter, net, block
            FROM ebr_ports
            WHERE bitstream = %s AND net IS NOT NULL
              AND port ~ '^J[ABCD]\\d+$'
        ) t
        GROUP BY port_letter, net
        HAVING count(distinct block) >= 3
    """, (bs_id,))
    main_group_nets = {row[1] for row in cur.fetchall()}  # set of net ids

    # All EBR ports with their bus metadata
    cur.execute("""
        SELECT ep.block, ep.port, ep.net, eb.bus_role, eb.bit_index
        FROM ebr_ports ep
        JOIN ebr_buses eb
          ON eb.bitstream = ep.bitstream
         AND eb.block     = ep.block
         AND eb.port      = ep.port
        WHERE ep.bitstream = %s AND ep.net IS NOT NULL
    """, (bs_id,))
    all_ebr_ports = cur.fetchall()  # (block, port, net, bus_role, bit_index)

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

        net_rows.append((bs_id, net, name, desc, 'estimate', 'auto_ebr'))

    bulk_insert(cur, _NET_NAME_INSERT, net_rows)
    conn.commit()
    cur.close()
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
    cur = conn.cursor()

    # Load all named pads (input and output)
    cur.execute("""
        SELECT pm.net_in, pm.net_out, pm.label, pm.direction
        FROM pad_map pm
        WHERE pm.bitstream = %s
    """, (bs_id,))
    pads = cur.fetchall()  # (net_in, net_out, label, direction)

    # Already-named nets and cells
    cur.execute("SELECT net  FROM net_names  WHERE bitstream = %s", (bs_id,))
    named_nets = {row[0] for row in cur.fetchall()}

    cur.execute("SELECT cell FROM cell_names WHERE bitstream = %s", (bs_id,))
    named_cells = {row[0] for row in cur.fetchall()}

    # Clock nets — skip these during hop propagation
    cur.execute("SELECT net FROM net_stats WHERE bitstream = %s AND is_clock = TRUE", (bs_id,))
    clock_nets = {row[0] for row in cur.fetchall()}

    # For hop-2 uniqueness: build map net → set of named-pad net_ins that reach
    # it within 1 hop (so we can check if a hop-2 net is already reachable at
    # hop 1 from another pad).
    cur.execute("""
        SELECT rch.src, rch.dst
        FROM reachability rch
        JOIN pad_map pm ON pm.bitstream = rch.bitstream AND pm.net_in = rch.src
        JOIN net_names nn ON nn.bitstream = pm.bitstream AND nn.net = pm.net_in
        WHERE rch.bitstream = %s AND rch.min_hops = 1
    """, (bs_id,))
    hop1_from_named_pad = {}   # dst_net → set of src pad net_ins
    for src, dst in cur.fetchall():
        hop1_from_named_pad.setdefault(dst, set()).add(src)

    net_rows  = []
    cell_rows = []
    added_nets = set()

    def add_net(net, name, desc):
        if net and net not in named_nets and net not in added_nets and net not in clock_nets:
            net_rows.append((bs_id, net, name, desc, 'estimate', 'auto_propagate'))
            added_nets.add(net)

    def add_cell(cell, name, desc):
        if cell and cell not in named_cells:
            cell_rows.append((bs_id, cell, name, desc, 'estimate'))

    for net_in, net_out, label, direction in pads:
        pad_lower = label.lower()

        # Only propagate from pads that have a name in net_names
        if net_in and net_in not in named_nets:
            continue

        if direction in ('input', 'inout', None) and net_in:
            # Fetch hops 1 and 2 from this pad's net_in
            cur.execute("""
                SELECT rch.dst, rch.min_hops
                FROM reachability rch
                WHERE rch.bitstream = %s AND rch.src = %s
                  AND rch.min_hops <= 2
            """, (bs_id, net_in))
            for dst_net, hops in cur.fetchall():
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
            cur.execute("""
                SELECT nf.cell, f.d
                FROM net_fanout nf
                JOIN ffs f ON f.bitstream = nf.bitstream AND f.cell = nf.cell
                WHERE nf.bitstream = %s AND nf.out_net = %s
                  AND nf.cell_type = 'FF'
            """, (bs_id, net_out))
            for ff_cell, d_net in cur.fetchall():
                add_net(d_net, f'{pad_lower}_d',
                        f'D input of output FF driving {label}')
                add_cell(ff_cell, f'ff_{pad_lower}',
                         f'Output FF driving {label} pad')

    bulk_insert(cur, _NET_NAME_INSERT,  net_rows)
    bulk_insert(cur, _CELL_NAME_INSERT, cell_rows)
    conn.commit()
    cur.close()
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
    cur = conn.cursor()

    # Load named nets
    cur.execute("SELECT net, name FROM net_names WHERE bitstream = %s", (bs_id,))
    net_name_map = {row[0]: row[1] for row in cur.fetchall()}

    # Already-named cells
    cur.execute("SELECT cell FROM cell_names WHERE bitstream = %s", (bs_id,))
    named_cells = {row[0] for row in cur.fetchall()}

    # Load all LUT cells with their Z net and fn (schema column is 'z')
    cur.execute("""
        SELECT cell, z, fn
        FROM luts
        WHERE bitstream = %s
    """, (bs_id,))
    luts = cur.fetchall()  # (cell, z_net, fn)

    cell_rows = []

    for cell, z_net, fn in luts:
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

        cell_rows.append((
            bs_id,
            cell,
            f'{prefix}_{net_name}',
            f'LUT driving {net_name}',
            'estimate',
        ))

    bulk_insert(cur, _CELL_NAME_INSERT, cell_rows)
    conn.commit()
    cur.close()
    return len(cell_rows)


# ---------------------------------------------------------------------------
# Pass 9: CDC synchroniser detection
# ---------------------------------------------------------------------------

_CREATE_CDC_TABLE = """
CREATE TABLE IF NOT EXISTS cdc_synchronisers (
    id         BIGSERIAL PRIMARY KEY,
    bitstream  INT  NOT NULL REFERENCES bitstreams(id) ON DELETE CASCADE,
    src_ff     TEXT NOT NULL,
    src_clk    TEXT NOT NULL,
    stage1_ff  TEXT NOT NULL,
    stage2_ff  TEXT NOT NULL,
    dst_clk    TEXT NOT NULL,
    UNIQUE(bitstream, stage1_ff)
)
"""


def _create_cdc_table(conn):
    """Create cdc_synchronisers table if it does not yet exist."""
    cur = conn.cursor()
    cur.execute(_CREATE_CDC_TABLE)
    conn.commit()
    cur.close()


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
    _create_cdc_table(conn)
    cur = conn.cursor()

    # Load net names for clock labelling
    cur.execute("SELECT net, name FROM net_names WHERE bitstream = %s", (bs_id,))
    net_name_map = {row[0]: row[1] for row in cur.fetchall()}

    def clk_label(clk_net):
        """Return semantic name if available, else strip leading 'n' from raw id."""
        nm = net_name_map.get(clk_net)
        if nm:
            return nm
        s = str(clk_net)
        return s.lstrip('n') if s.startswith('n') else s

    # Load all FFs: cell, q, d, clk, ce
    cur.execute("""
        SELECT cell, q, d, clk, ce
        FROM ffs
        WHERE bitstream = %s
    """, (bs_id,))
    all_ffs = cur.fetchall()

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
    cur.execute("""
        SELECT cell, z
        FROM luts
        WHERE bitstream = %s
    """, (bs_id,))
    lut_by_output = {}  # z_net → cell
    for lut_cell, z_net in cur.fetchall():
        lut_by_output[z_net] = lut_cell

    # Build lut z → input nets for 1-LUT hop via LUT (using luts columns a/b/c/d)
    cur.execute("""
        SELECT cell, a, b, c, d
        FROM luts
        WHERE bitstream = %s
    """, (bs_id,))
    lut_inputs = {}  # lut_cell → list of input nets
    for lut_cell, a, b, c, dd in cur.fetchall():
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
    cdc_rows = []
    for src_ff, src_clk, stage1_ff, stage2_ff, dst_clk in synchronisers:
        cdc_rows.append((bs_id, src_ff, src_clk, stage1_ff, stage2_ff, dst_clk))

    if cdc_rows:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO cdc_synchronisers
                (bitstream, src_ff, src_clk, stage1_ff, stage2_ff, dst_clk)
            VALUES %s
            ON CONFLICT (bitstream, stage1_ff) DO NOTHING
        """, cdc_rows, page_size=500)

    # Name stage1 and stage2 FF cells
    named_cells_cur = set()
    cur.execute("SELECT cell FROM cell_names WHERE bitstream = %s", (bs_id,))
    named_cells_cur = {row[0] for row in cur.fetchall()}

    cell_rows = []
    for src_ff, src_clk, stage1_ff, stage2_ff, dst_clk in synchronisers:
        src_label = clk_label(src_clk)
        dst_label = clk_label(dst_clk)

        name1 = f'sync1_{src_label}_{dst_label}'
        name2 = f'sync2_{src_label}_{dst_label}'

        if stage1_ff not in named_cells_cur:
            cell_rows.append((
                bs_id, stage1_ff, name1,
                f'CDC sync stage 1: {src_label} → {dst_label}',
                'estimate',
            ))
        if stage2_ff not in named_cells_cur:
            cell_rows.append((
                bs_id, stage2_ff, name2,
                f'CDC sync stage 2: {src_label} → {dst_label}',
                'estimate',
            ))

    # Use source='auto_cdc' — need a custom insert for cell_names with source column
    # cell_names schema: (bitstream, cell, name, description, confidence)
    # source not stored in cell_names; use standard insert
    bulk_insert(cur, _CELL_NAME_INSERT, cell_rows)
    conn.commit()
    cur.close()
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
    conn = connect()
    cur  = conn.cursor()
    cur.execute("SELECT id FROM bitstreams WHERE label = %s", (args.bitstream,))
    row = cur.fetchone()
    if not row:
        die(f"Bitstream {args.bitstream!r} not found — run load.py first")
    bs_id = row[0]
    cur.close()
    conn.close()

    wall_start = time.time()
    timings    = []

    def run_pass(label, fn):
        """Open a fresh connection, run fn(conn), close, record timing."""
        print(f"{label}…", flush=True)
        t   = time.time()
        c   = connect()
        result  = fn(c)
        c.close()
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
    summary_conn = connect()
    summary_cur  = summary_conn.cursor()
    summary_cur.execute("""
        SELECT
            (SELECT count(*) FROM nets       WHERE bitstream = %s) AS total_nets,
            (SELECT count(*) FROM net_names  WHERE bitstream = %s) AS named_nets,
            (SELECT count(*) FROM ffs        WHERE bitstream = %s) AS total_ffs,
            (SELECT count(*) FROM cell_names WHERE bitstream = %s) AS named_cells,
            (SELECT count(*) FROM luts       WHERE bitstream = %s) AS total_luts,
            (SELECT count(*) FROM cell_names cn
               JOIN luts l ON l.bitstream = cn.bitstream AND l.cell = cn.cell
               WHERE cn.bitstream = %s) AS named_luts
    """, (bs_id, bs_id, bs_id, bs_id, bs_id, bs_id))
    total_nets, named_nets, total_ffs, named_cells, total_luts, named_luts = \
        summary_cur.fetchone()
    summary_cur.close()
    summary_conn.close()

    net_pct  = 100.0 * named_nets  / total_nets  if total_nets  else 0
    cell_pct = 100.0 * named_cells / total_ffs   if total_ffs   else 0
    lut_pct  = 100.0 * named_luts  / total_luts  if total_luts  else 0
    print(f"\n  Coverage: {named_nets}/{total_nets} nets named ({net_pct:.1f}%),",
          f"{named_cells}/{total_ffs} FF cells named ({cell_pct:.1f}%),",
          f"{named_luts}/{total_luts} LUT cells named ({lut_pct:.1f}%)")


if __name__ == "__main__":
    main()
