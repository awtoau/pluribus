#!/usr/bin/env python3
"""Pluribus — structural analysis stage 3.

Runs after reach2.py. Eight passes, each building one table:

  Pass 1  lut_symbolic      — expand each LUT's fn into a readable boolean
                              expression with real net names substituted in
  Pass 2  ff_d_functions    — each FF's D input expressed as a symbolic formula
  Pass 3  shift_registers   — chains of FFs sharing a clock/enable (Q feeds next D)
                              written into the 'patterns' + 'shift_reg_bits' tables
  Pass 4  clock_crossings   — FFs whose input cone contains a FF on a different clock
  Pass 5  ebr_buses         — group block-RAM ports into write/read data/addr/ctrl buses
  Pass 6  net_stats         — fan-in, fan-out, is_clock, is_const, is_boundary per net
  Pass 7  cone_hashes       — SHA1 of each FF's input-cone topology (no net names, so
                              structurally identical sub-circuits get identical hashes)
  Pass 8  const_nets        — nets provably stuck at 0 or 1, propagated through LUTs

Usage
-----
  python3 fpga/pluribus/reach3.py [--bitstream V07] [--workers 24] [--depth 4]
"""

import argparse
import hashlib
import json
import math
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import connect, die, execute_values


# ---------------------------------------------------------------------------
# Shared insert helper
# ---------------------------------------------------------------------------

def bulk_insert(cursor, sql, rows):
    """Bulk-insert rows using execute_values. No-op on empty list."""
    execute_values(cursor, sql, rows, page_size=2000)


# ---------------------------------------------------------------------------
# DDL for the six new tables created by this stage
# ---------------------------------------------------------------------------

NEW_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS lut_symbolic (
    id         BIGSERIAL PRIMARY KEY,
    bitstream  INT  NOT NULL REFERENCES bitstreams(id) ON DELETE CASCADE,
    lut_cell   TEXT NOT NULL,
    -- Full boolean expression with input nets substituted in.
    -- Example: "AND(n307, XOR(JUPDATE, n1047))"
    expr       TEXT NOT NULL,
    -- How many LUT levels deep the expansion went (0 = leaf LUT)
    depth      INT  NOT NULL DEFAULT 0,
    UNIQUE (bitstream, lut_cell)
);

CREATE TABLE IF NOT EXISTS clock_crossings (
    id        BIGSERIAL PRIMARY KEY,
    bitstream INT  NOT NULL REFERENCES bitstreams(id) ON DELETE CASCADE,
    -- The FF that receives a signal from a different clock domain
    dst_ff    TEXT NOT NULL,
    dst_clk   TEXT NOT NULL,
    -- The FF whose Q output is the crossing source
    src_ff    TEXT NOT NULL,
    src_clk   TEXT NOT NULL,
    hops      INT  NOT NULL,
    UNIQUE (bitstream, dst_ff, src_ff)
);
CREATE INDEX IF NOT EXISTS idx_cc_dst ON clock_crossings(bitstream, dst_ff);
CREATE INDEX IF NOT EXISTS idx_cc_src ON clock_crossings(bitstream, src_ff);

CREATE TABLE IF NOT EXISTS ebr_buses (
    id        SERIAL PRIMARY KEY,
    bitstream INT  NOT NULL REFERENCES bitstreams(id) ON DELETE CASCADE,
    -- EBR block identifier, e.g. "R6C1"
    block     TEXT NOT NULL,
    -- Which logical bus this port belongs to
    bus_role  TEXT NOT NULL,  -- 'write_data','read_data','write_addr','read_addr','ctrl'
    bit_index INT  NOT NULL,
    port      TEXT NOT NULL,  -- raw port name, e.g. "JA3"
    net       TEXT,           -- connected fabric net (may be NULL if unconnected)
    UNIQUE (bitstream, block, bus_role, bit_index)
);

CREATE TABLE IF NOT EXISTS net_stats (
    id          SERIAL  PRIMARY KEY,
    bitstream   INT     NOT NULL REFERENCES bitstreams(id) ON DELETE CASCADE,
    net         TEXT    NOT NULL,
    -- How many cell inputs this net drives (0 = dead net)
    fanout      INT     NOT NULL DEFAULT 0,
    -- How many cells produce this net (normally 0 or 1; >1 = problem)
    fanin       INT     NOT NULL DEFAULT 0,
    is_clock    BOOLEAN NOT NULL DEFAULT FALSE,
    -- TRUE if the net is driven by a constant source (CONST LUT or stuck FF)
    is_const    BOOLEAN NOT NULL DEFAULT FALSE,
    -- TRUE if the net connects to a physical pad or EFB port
    is_boundary BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (bitstream, net)
);

CREATE TABLE IF NOT EXISTS cone_hashes (
    id         SERIAL PRIMARY KEY,
    bitstream  INT  NOT NULL REFERENCES bitstreams(id) ON DELETE CASCADE,
    ff_cell    TEXT NOT NULL,
    -- SHA1 of the topological cone structure (init values + connectivity, no net names)
    cone_hash  TEXT NOT NULL,
    -- Number of LUTs in this FF's input cone
    cone_size  INT  NOT NULL,
    UNIQUE (bitstream, ff_cell)
);
CREATE INDEX IF NOT EXISTS idx_cone_hash ON cone_hashes(bitstream, cone_hash);

CREATE TABLE IF NOT EXISTS const_nets (
    id          SERIAL PRIMARY KEY,
    bitstream   INT  NOT NULL REFERENCES bitstreams(id) ON DELETE CASCADE,
    net         TEXT NOT NULL,
    const_value TEXT NOT NULL,  -- '0' or '1'
    UNIQUE (bitstream, net)
);
"""


def create_new_tables(conn):
    """Apply the DDL for tables this stage owns. Safe to re-run (IF NOT EXISTS)."""
    cur = conn.cursor()
    cur.execute(NEW_TABLES_DDL)
    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# LUT init → boolean expression (Quine-McCluskey for 4 variables)
# ---------------------------------------------------------------------------

def _qm_minimise(init_str, port_names):
    """Convert a 16-bit LUT init string to a minimal SOP boolean expression.

    init_str: 16-character binary string, bit k = output when inputs = k
              (bit 0 = LSB = {d=0,c=0,b=0,a=0}, bit 15 = {d=1,c=1,b=1,a=1})
    port_names: list of 4 net names [a, b, c, d] (None = unconnected/NC)

    Returns a string like "(!a & b) | (c & d)" or "1" / "0".
    """
    if len(init_str) != 16:
        return f"INIT({init_str})"

    # NC ports are fixed at 0 by machxo2_lift.  Pre-filter minterms to only
    # those reachable (NC bits = 0), then treat NC columns as don't-care in QM.
    nc_mask = sum(1 << i for i, p in enumerate(port_names) if p is None)
    ones = [i for i in range(16)
            if init_str[15 - i] == '1' and (i & nc_mask) == 0]
    if not ones:
        return '0'
    # Also check if all reachable minterms are 1
    reachable = [i for i in range(16) if (i & nc_mask) == 0]
    if set(ones) == set(reachable):
        return '1'

    # Determine which inputs are actually connected (not NC)
    active = [i for i, p in enumerate(port_names) if p is not None]
    labels = ['a', 'b', 'c', 'd']

    # Quine-McCluskey prime implicant generation
    def covers(implicant, minterm):
        for bit in range(4):
            v = (implicant >> (bit * 2)) & 3
            if v != 2 and v != ((minterm >> bit) & 1):
                return False
        return True

    # Encode implicants as pairs of ints: (care_mask, value)
    # Use a simpler approach: iterate standard QM grouping
    # implicant = list of (value, mask) where mask bit 1 = don't-care
    def can_combine(a_val, a_mask, b_val, b_mask):
        if a_mask != b_mask:
            return False
        diff = a_val ^ b_val
        return diff != 0 and (diff & (diff - 1)) == 0  # exactly one bit differs

    def combine(a_val, a_mask, b_val, _b_mask):
        diff = a_val ^ b_val
        return (a_val & ~diff) & 0xF, a_mask | diff

    # Start: one implicant per minterm
    current = {(v, 0) for v in ones}
    prime_implicants = set()
    while current:
        next_level = set()
        used = set()
        items = list(current)
        for i, (av, am) in enumerate(items):
            for bv, bm in items[i+1:]:
                if can_combine(av, am, bv, bm):
                    cv, cm = combine(av, am, bv, bm)
                    next_level.add((cv, cm))
                    used.add((av, am))
                    used.add((bv, bm))
        prime_implicants |= current - used
        current = next_level

    # Essential prime implicant cover (greedy — 4 variables is tiny)
    uncovered = set(ones)
    selected = []
    # Sort PIs by number of minterms covered (descending) for greedy
    def pi_minterms(pi):
        v, m = pi
        dc_bits = [b for b in range(4) if (m >> b) & 1]
        result = []
        def expand(idx, cur_v):
            if idx == len(dc_bits):
                result.append(cur_v)
                return
            b = dc_bits[idx]
            expand(idx + 1, cur_v)
            expand(idx + 1, cur_v | (1 << b))
        expand(0, v & ~m)
        return result
    pi_covered = {pi: set(pi_minterms(pi)) for pi in prime_implicants}
    while uncovered:
        best = max(pi_covered, key=lambda p: len(pi_covered[p] & uncovered))
        selected.append(best)
        uncovered -= pi_covered[best]
        del pi_covered[best]

    # Render each selected prime implicant as a product term.
    # NC (unconnected) ports are fixed at 0 by machxo2_lift — they are always
    # in the 0-state so they never appear in a positive literal, and since all
    # minterms already have them at 0, the QM will mark them don't-care.  Skip
    # them in the output so they don't pollute the expression with NC0/NC1/...
    def render_pi(v, m):
        terms = []
        for bit in range(4):
            if (m >> bit) & 1:
                continue  # don't-care
            name = port_names[bit]
            if name is None:
                continue  # NC bit: always 0, already factored into the minterms
            if (v >> bit) & 1:
                terms.append(name)
            else:
                terms.append(f'!{name}')
        if not terms:
            return '1'
        return ' & '.join(terms)

    products = [render_pi(v, m) for v, m in selected]
    if len(products) == 1:
        return products[0]
    return ' | '.join(f'({p})' if ' & ' in p else p for p in products)


# ---------------------------------------------------------------------------
# Pass 1: lut_symbolic — expand each LUT's fn tag into a full expression
# ---------------------------------------------------------------------------

def _expand_lut_expressions(lut_rows, max_depth):
    """
    Return {lut_cell: (expr_string, expansion_depth)} for every LUT.

    How it works
    ------------
    Each LUT has a semantic fn tag like AND(a,b) or MUX(sel,i0,i1) and four
    input port columns (a, b, c, d) that hold the net names wired to those
    ports.  We substitute the port letters in fn with the actual net names,
    then recurse into any input that is itself a LUT output — up to max_depth
    levels.  COMBO/COMBO2/COMBO3/COMBO4: decode from 16-bit init truth table
    using Quine-McCluskey minimisation to produce a minimal SOP expression.

    lut_rows: list of (cell, fn, port_a, port_b, port_c, port_d, out_z, init)
    """
    # Which LUT cell produces each net (used to decide whether to recurse)
    lut_driving = {}      # net_name -> lut_cell
    lut_details = {}      # lut_cell -> (fn, {port: net}, init)

    for cell, fn, pa, pb, pc, pd, out_z, init in lut_rows:
        lut_details[cell] = (fn, {'a': pa, 'b': pb, 'c': pc, 'd': pd}, init)
        if out_z:
            lut_driving[out_z] = cell

    cache = {}   # lut_cell -> (expr, depth) — memoised to avoid re-expanding

    def expand_cell(cell, remaining_depth):
        if cell in cache:
            return cache[cell]

        fn, port_nets, init = lut_details[cell]

        def resolve_port(net, depth_left):
            """Return either the net name (leaf) or the expanded sub-expression."""
            if net is None:
                return 'NC'
            if depth_left <= 0 or net not in lut_driving:
                return net   # leaf: just use the net name
            sub_cell = lut_driving[net]
            sub_expr, _ = expand_cell(sub_cell, depth_left)
            return sub_expr

        # COMBO tags: decode the 16-bit init truth table with QM minimisation
        if fn is None or fn.startswith('COMBO'):
            if init and len(init) == 16 and all(c in '01' for c in init):
                port_name_list = [port_nets.get(p) for p in ('a', 'b', 'c', 'd')]
                expr = _qm_minimise(init, port_name_list)
            else:
                named_inputs = [
                    f"{port}={resolve_port(port_nets[port], remaining_depth - 1)}"
                    for port in ('a', 'b', 'c', 'd')
                    if port_nets[port] is not None
                ]
                expr = f"COMBO({', '.join(named_inputs)})" if named_inputs else "COMBO()"
            depth = 0

        elif fn == 'CONST0':
            expr, depth = '0', 0

        elif fn == 'CONST1':
            expr, depth = '1', 0

        else:
            # Structured tag: AND(a,b), XOR(c,d), MUX(sel,i0,i1), BUF(a), INV(d) ...
            # The letters a/b/c/d in the fn string refer to the four port columns.
            # Replace each standalone port letter with its resolved net/expression.
            def replace_port_letter(match):
                letter = match.group(0)
                net = port_nets.get(letter)
                if net is None:
                    return 'NC'
                return resolve_port(net, remaining_depth - 1)

            expr = re.sub(r'\b([abcd])\b', replace_port_letter, fn)
            depth = 0

        depth_used = max_depth - remaining_depth
        result = (expr, depth_used)
        cache[cell] = result
        return result

    return {cell: expand_cell(cell, max_depth) for cell in lut_details}


def pass_lut_symbolic(bs_id, conn, max_depth):
    cur = conn.cursor()
    cur.execute("SELECT cell, fn, a, b, c, d, z, init FROM luts WHERE bitstream=%s", (bs_id,))
    lut_rows = cur.fetchall()
    cur.close()

    if not lut_rows:
        die(f"No LUTs for bitstream {bs_id} — was load.py run?")

    expanded = _expand_lut_expressions(lut_rows, max_depth)

    cur = conn.cursor()
    cur.execute("DELETE FROM lut_symbolic WHERE bitstream=%s", (bs_id,))
    rows = [(bs_id, cell, expr, depth) for cell, (expr, depth) in expanded.items()]
    bulk_insert(cur, """
        INSERT INTO lut_symbolic (bitstream, lut_cell, expr, depth)
        VALUES %s ON CONFLICT DO NOTHING
    """, rows)
    conn.commit()
    cur.close()
    return len(rows)


# ---------------------------------------------------------------------------
# Pass 2: ff_d_functions — symbolic D-input expression per FF
# ---------------------------------------------------------------------------

def pass_ff_d_functions(bs_id, conn):
    """
    For every FF, express its D input as a human-readable formula.

    Priority:
      1. d = '1''b0' or '1''b1' → literal '0' or '1'
      2. d is a LUT's output net → use lut_symbolic.expr for that LUT
      3. d is a pad's input net  → use the pad label (e.g. "ADC_D0A")
      4. otherwise               → use the raw net name (another FF's Q or unknown)

    pad_inputs is filled from pad_ff_influence: which physical pads can
    transitively reach this FF (regardless of how the D path is expressed).
    """
    cur = conn.cursor()

    # Load FFs
    cur.execute("SELECT cell, d, ce FROM ffs WHERE bitstream=%s", (bs_id,))
    all_ffs = cur.fetchall()

    # Load symbolic expressions from pass 1
    cur.execute("SELECT lut_cell, expr, depth FROM lut_symbolic WHERE bitstream=%s", (bs_id,))
    symbolic_by_lut = {lut_cell: (expr, depth) for lut_cell, expr, depth in cur.fetchall()}

    # Which LUT cell produces each net
    cur.execute("SELECT cell, z FROM luts WHERE bitstream=%s AND z IS NOT NULL", (bs_id,))
    lut_driving = {out_z: cell for cell, out_z in cur.fetchall()}

    # Pad label by the net that comes in from that pad
    cur.execute("""
        SELECT net_in, label FROM pad_map
        WHERE bitstream=%s AND net_in IS NOT NULL
    """, (bs_id,))
    pad_label_by_net = {net_in: label for net_in, label in cur.fetchall()}

    # Which pads transitively reach each FF (from pad_ff_influence)
    cur.execute("""
        SELECT ff_cell, array_agg(pad_label ORDER BY pad_label)
        FROM pad_ff_influence WHERE bitstream=%s
        GROUP BY ff_cell
    """, (bs_id,))
    pad_inputs_by_ff = {ff_cell: pads for ff_cell, pads in cur.fetchall()}

    cur.execute("DELETE FROM ff_d_functions WHERE bitstream=%s", (bs_id,))

    output_rows = []
    for ff_cell, d_net, _ce in all_ffs:
        if d_net is None or d_net == "1'b0":
            fn_expr    = '0'
            expr_depth = 0
        elif d_net == "1'b1":
            fn_expr    = '1'
            expr_depth = 0
        elif d_net in lut_driving:
            driving_lut        = lut_driving[d_net]
            fn_expr, expr_depth = symbolic_by_lut.get(driving_lut, (d_net, 0))
        elif d_net in pad_label_by_net:
            fn_expr    = pad_label_by_net[d_net]
            expr_depth = 0
        else:
            fn_expr    = d_net   # raw net name (another FF's Q or unresolved)
            expr_depth = 0

        pad_inputs = pad_inputs_by_ff.get(ff_cell)
        output_rows.append((bs_id, ff_cell, fn_expr, expr_depth, pad_inputs))

    bulk_insert(cur, """
        INSERT INTO ff_d_functions (bitstream, ff_cell, fn_expr, depth, pad_inputs)
        VALUES %s ON CONFLICT DO NOTHING
    """, output_rows)
    conn.commit()
    cur.close()
    return len(output_rows)


# ---------------------------------------------------------------------------
# Pass 3: shift_registers — detect FF chains with matching CLK + CE
# ---------------------------------------------------------------------------

def _find_buf_lut_shortcuts(lut_rows):
    """
    Return {input_net: output_net} for LUTs whose fn is a plain BUF (not INV).

    A BUF LUT is a single-input buffer: fn='BUF(a)' means output = input on port a.
    We allow one BUF LUT between FF.Q and the next FF.D when building chains.
    """
    buf_shortcuts = {}
    for _cell, fn, pa, pb, pc, pd, out_z in lut_rows:
        if fn and fn.startswith('BUF(') and out_z:
            match = re.match(r'BUF\(([abcd])\)', fn)
            if match:
                port        = match.group(1)
                driving_net = {'a': pa, 'b': pb, 'c': pc, 'd': pd}.get(port)
                if driving_net:
                    buf_shortcuts[driving_net] = out_z
    return buf_shortcuts


def _build_ff_q_to_d_edges(ff_rows, buf_shortcuts):
    """
    Return {src_ff_cell: (dst_ff_cell, dst_clk, dst_ce, via_buf)} for every
    FF whose Q net feeds directly (or via one BUF LUT) into another FF's D.

    ff_rows: list of (cell, clk, ce, d, q)
    """
    ff_by_q_net = {}   # q_net -> (cell, clk, ce)
    ff_by_d_net = {}   # d_net -> (cell, clk, ce)

    for cell, clk, ce, d_net, q_net in ff_rows:
        if q_net and not q_net.startswith("1'b"):
            ff_by_q_net[q_net] = (cell, clk, ce)
        if d_net and not d_net.startswith("1'b"):
            ff_by_d_net[d_net] = (cell, clk, ce)

    edges = {}   # src_ff_cell -> (dst_ff_cell, dst_clk, dst_ce, via_buf)

    for q_net, (src_cell, _src_clk, _src_ce) in ff_by_q_net.items():
        if q_net in ff_by_d_net:
            # Direct Q→D connection
            dst_cell, dst_clk, dst_ce = ff_by_d_net[q_net]
            edges[src_cell] = (dst_cell, dst_clk, dst_ce, False)
        elif q_net in buf_shortcuts:
            # Q → BUF_LUT → D connection
            buf_output = buf_shortcuts[q_net]
            if buf_output in ff_by_d_net:
                dst_cell, dst_clk, dst_ce = ff_by_d_net[buf_output]
                edges[src_cell] = (dst_cell, dst_clk, dst_ce, True)

    return edges


def _walk_ff_chains(edges, ff_by_q_net):
    """
    Walk the Q→D edge graph and return all maximal chains of length >= 2
    where every step has the same CLK and CE net.

    Returns list of (chain_cells, clk_net, ce_net).
    """
    cells_that_are_destinations = {dst for dst, _clk, _ce, _buf in edges.values()}
    visited = set()
    chains  = []

    for start_cell in ff_by_q_net:
        if start_cell in visited:
            continue
        # Only start from chain heads — cells that nothing else points into
        if start_cell in cells_that_are_destinations:
            continue
        if start_cell not in edges:
            continue

        src_clk = ff_by_q_net[start_cell][1]
        src_ce  = ff_by_q_net[start_cell][2]

        chain          = [start_cell]
        seen_in_chain  = {start_cell}
        current        = start_cell

        while current in edges:
            next_cell, next_clk, next_ce, _buf = edges[current]
            if next_clk != src_clk or next_ce != src_ce:
                break
            if next_cell in seen_in_chain:
                break   # cycle guard
            chain.append(next_cell)
            seen_in_chain.add(next_cell)
            current = next_cell

        visited.update(chain)
        if len(chain) >= 2:
            chains.append((chain, src_clk, src_ce))

    return chains


def pass_shift_registers(bs_id, conn):
    cur = conn.cursor()

    cur.execute("SELECT cell, clk, ce, d, q FROM ffs WHERE bitstream=%s", (bs_id,))
    ff_rows = cur.fetchall()

    cur.execute("SELECT cell, fn, a, b, c, d, z FROM luts WHERE bitstream=%s", (bs_id,))
    lut_rows = cur.fetchall()

    # Build the indexes needed for chain detection
    ff_by_q_net   = {}
    ff_q_by_cell  = {}   # ff_cell -> q_net  (for writing shift_reg_bits)
    for cell, clk, ce, d_net, q_net in ff_rows:
        if q_net and not q_net.startswith("1'b"):
            ff_by_q_net[q_net] = (cell, clk, ce)
        if q_net:
            ff_q_by_cell[cell] = q_net

    buf_shortcuts = _find_buf_lut_shortcuts(lut_rows)
    edges         = _build_ff_q_to_d_edges(ff_rows, buf_shortcuts)
    chains        = _walk_ff_chains(edges, ff_by_q_net)

    # Remove old shift-register patterns for this bitstream before writing new ones
    cur.execute("DELETE FROM patterns WHERE bitstream=%s AND pattern_type='shift_reg'", (bs_id,))
    conn.commit()

    n_chains     = 0
    n_total_bits = 0

    for chain_cells, clk_net, ce_net in chains:
        label  = f"shift_reg_{n_chains}"
        detail = json.dumps({
            "length":  len(chain_cells),
            "clk_net": clk_net,
            "ce_net":  ce_net,
            "head_ff": chain_cells[0],
            "tail_ff": chain_cells[-1],
        })
        cur.execute("""
            INSERT INTO patterns (bitstream, pattern_type, label, detail)
            VALUES (%s, 'shift_reg', %s, %s::jsonb)
            RETURNING id
        """, (bs_id, label, detail))
        pattern_id = cur.fetchone()[0]

        bit_rows = [
            (pattern_id, bit_index, ff_cell,
             ff_q_by_cell.get(ff_cell, ''), clk_net, ce_net)
            for bit_index, ff_cell in enumerate(chain_cells)
        ]
        bulk_insert(cur, """
            INSERT INTO shift_reg_bits
                (pattern_id, bit_index, ff_cell, q_net, clk_net, load_en_net)
            VALUES %s
        """, bit_rows)

        n_chains     += 1
        n_total_bits += len(chain_cells)

    conn.commit()
    cur.close()
    return n_chains, n_total_bits


# ---------------------------------------------------------------------------
# Pass 4: clock_crossings — FFs whose input cone contains a different-domain FF
# ---------------------------------------------------------------------------

def pass_clock_crossings(bs_id, conn):
    """
    Pure SQL: find every (src_ff, dst_ff) pair where:
      - src_ff.Q appears in dst_ff's input cone (ff_cones.cone_type='input')
      - src_ff and dst_ff are on different clock nets

    These are potential metastability hazards — signals crossing clock domains
    without a synchroniser.
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM clock_crossings WHERE bitstream=%s", (bs_id,))
    cur.execute("""
        INSERT INTO clock_crossings
            (bitstream, dst_ff, dst_clk, src_ff, src_clk, hops)
        SELECT
            fc.bitstream,
            fc.ff_cell        AS dst_ff,
            cd_dst.clk_net    AS dst_clk,
            src_ff.cell       AS src_ff,
            cd_src.clk_net    AS src_clk,
            fc.min_hops       AS hops
        FROM ff_cones fc
        -- fc.net is in dst_ff's input cone; check if it is a Q output of some src_ff
        JOIN ffs src_ff
            ON src_ff.bitstream = fc.bitstream
           AND src_ff.q         = fc.net
        -- clock domain of the destination FF
        JOIN clock_domains cd_dst
            ON cd_dst.bitstream = fc.bitstream
           AND cd_dst.ff_cell   = fc.ff_cell
        -- clock domain of the source FF
        JOIN clock_domains cd_src
            ON cd_src.bitstream = fc.bitstream
           AND cd_src.ff_cell   = src_ff.cell
        WHERE fc.bitstream   = %s
          AND fc.cone_type   = 'input'
          AND cd_src.clk_net <> cd_dst.clk_net
        ON CONFLICT (bitstream, dst_ff, src_ff)
            DO UPDATE SET hops = EXCLUDED.hops
    """, (bs_id,))
    n = cur.rowcount
    conn.commit()
    cur.close()
    return n


# ---------------------------------------------------------------------------
# Pass 5: ebr_buses — classify EBR ports into logical buses
# ---------------------------------------------------------------------------

# EBR port naming convention: J<letter><index>
#   A0–A17  write data bus, bits 0–17
#   B0–B17  read data bus, bits 0–17
#   C0–C8   write address bus, bits 0–8
#   D0–D8   read address bus, bits 0–8
#   E/F/G/H control ports (grouped with a compound bit_index to avoid collisions)

_EBR_PORT_PATTERN = re.compile(r'^J([A-H])(\d+)$', re.IGNORECASE)

_EBR_LETTER_TO_ROLE = {
    'A': 'write_data',
    'B': 'read_data',
    'C': 'write_addr',
    'D': 'read_addr',
    'E': 'ctrl',
    'F': 'ctrl',
    'G': 'ctrl',
    'H': 'ctrl',
}


def _classify_ebr_port(port_name):
    """
    Return (bus_role, bit_index) for a port like "JA3" or "JE1", or None
    if the name doesn't match the expected pattern.

    ctrl ports (E/F/G/H) get a compound bit_index = (letter_offset * 32) + bit
    so they don't collide with each other in the same table.
    """
    match = _EBR_PORT_PATTERN.match(port_name)
    if not match:
        return None
    letter    = match.group(1).upper()
    bit_index = int(match.group(2))
    role      = _EBR_LETTER_TO_ROLE.get(letter)
    if role is None:
        return None
    if role == 'ctrl':
        letter_offset = ord(letter) - ord('E')
        bit_index     = letter_offset * 32 + bit_index
    return (role, bit_index)


def pass_ebr_buses(bs_id, conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM ebr_buses WHERE bitstream=%s", (bs_id,))

    cur.execute("SELECT block, port, net FROM ebr_ports WHERE bitstream=%s", (bs_id,))
    ebr_ports = cur.fetchall()

    output_rows = []
    skipped     = 0
    for block, port_name, net in ebr_ports:
        classified = _classify_ebr_port(port_name)
        if classified is None:
            skipped += 1
            continue
        role, bit_index = classified
        output_rows.append((bs_id, block, role, bit_index, port_name, net))

    bulk_insert(cur, """
        INSERT INTO ebr_buses (bitstream, block, bus_role, bit_index, port, net)
        VALUES %s ON CONFLICT DO NOTHING
    """, output_rows)
    conn.commit()
    cur.close()

    if skipped:
        print(f"  ({skipped} EBR ports skipped — unrecognised name format)", flush=True)
    return len(output_rows)


# ---------------------------------------------------------------------------
# Pass 6: net_stats — fan-in, fan-out, and flag bits for every net
# ---------------------------------------------------------------------------

def pass_net_stats(bs_id, conn):
    """
    For every net in the design, record:
      fanout      — how many cell inputs it drives
      fanin       — how many cells produce it (normally 0 or 1)
      is_clock    — it is the CLK net for at least one FF
      is_const    — it is driven by a constant source (CONST0/CONST1 LUT or stuck FF)
      is_boundary — it connects to a physical pad or an EFB port
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM net_stats WHERE bitstream=%s", (bs_id,))

    # Fan-out: count how many cell inputs are driven by each net
    cur.execute("""
        SELECT net, count(*) FROM net_fanout WHERE bitstream=%s GROUP BY net
    """, (bs_id,))
    fanout_by_net = dict(cur.fetchall())

    # Fan-in: count how many cells produce each net
    cur.execute("""
        SELECT out_net, count(*) FROM net_fanout
        WHERE bitstream=%s AND out_net IS NOT NULL
        GROUP BY out_net
    """, (bs_id,))
    fanin_by_net = dict(cur.fetchall())

    # Clock nets: appear as clk_net in clock_domains
    cur.execute("SELECT DISTINCT clk_net FROM clock_domains WHERE bitstream=%s", (bs_id,))
    clock_nets = {row[0] for row in cur.fetchall()}

    # Const nets from LUTs with constant output
    cur.execute("""
        SELECT z FROM luts
        WHERE bitstream=%s AND z IS NOT NULL AND fn IN ('CONST0','CONST1')
    """, (bs_id,))
    const_nets = {row[0] for row in cur.fetchall()}

    # Also: FFs stuck at reset — d='1'b0' with no CE (or CE='1'b0') → Q is const 0
    cur.execute("""
        SELECT q FROM ffs
        WHERE bitstream=%s AND q IS NOT NULL
          AND d = '1''b0'
          AND (ce = '1''b0' OR ce IS NULL)
    """, (bs_id,))
    for (q_net,) in cur.fetchall():
        const_nets.add(q_net)

    # Boundary nets: physical pad nets + EFB port nets
    cur.execute("""
        SELECT net_in  FROM pad_map WHERE bitstream=%s AND net_in  IS NOT NULL
        UNION ALL
        SELECT net_out FROM pad_map WHERE bitstream=%s AND net_out IS NOT NULL
        UNION ALL
        SELECT net     FROM efb_ports WHERE bitstream=%s AND net IS NOT NULL
    """, (bs_id, bs_id, bs_id))
    boundary_nets = {row[0] for row in cur.fetchall()}

    # All nets in the design
    cur.execute("SELECT name FROM nets WHERE bitstream=%s", (bs_id,))
    all_net_names = [row[0] for row in cur.fetchall()]

    output_rows = [
        (bs_id, net,
         fanout_by_net.get(net, 0),
         fanin_by_net.get(net, 0),
         net in clock_nets,
         net in const_nets,
         net in boundary_nets)
        for net in all_net_names
    ]

    bulk_insert(cur, """
        INSERT INTO net_stats
            (bitstream, net, fanout, fanin, is_clock, is_const, is_boundary)
        VALUES %s ON CONFLICT DO NOTHING
    """, output_rows)
    conn.commit()
    cur.close()
    return len(output_rows)


# ---------------------------------------------------------------------------
# Pass 7: cone_hashes — structural hash of each FF's input cone
# ---------------------------------------------------------------------------

def _topology_hash_for_ff(d_net, lut_driving, lut_topology, max_depth):
    """
    BFS from d_net through the LUT cone.  Collect topology tuples at each level:
      (bfs_level, lut_init, n_leaf_inputs, n_lut_inputs)

    We deliberately do NOT include net names — only the init table and how
    many inputs are leaves vs LUT outputs.  Two structurally identical sub-
    circuits will therefore hash the same even if they have different net names.

    Returns (hash_hex, cone_size_in_luts).
    """
    # Handle constants and non-LUT D inputs quickly
    if d_net is None or d_net.startswith("1'b"):
        return hashlib.sha1(f"CONST:{d_net}".encode()).hexdigest(), 0

    if d_net not in lut_driving:
        # D is driven by another FF's Q or an unknown source — not a LUT cone
        return hashlib.sha1(b"LEAF_FF_OR_PAD").hexdigest(), 0

    visited_cells      = {}   # lut_cell -> bfs_level
    queue              = deque([(lut_driving[d_net], 0)])
    visited_cells[lut_driving[d_net]] = 0
    topology_elements  = []

    while queue:
        cell, level = queue.popleft()

        if level >= max_depth:
            topology_elements.append((level, 'TRUNCATED', 0, 0))
            continue

        init, input_nets = lut_topology.get(cell, ('?' * 16, [None, None, None, None]))

        n_lut_inputs  = 0
        n_leaf_inputs = 0
        for input_net in input_nets:
            if input_net is None:
                continue
            if input_net in lut_driving:
                n_lut_inputs += 1
                child_cell = lut_driving[input_net]
                if child_cell not in visited_cells and level + 1 < max_depth:
                    visited_cells[child_cell] = level + 1
                    queue.append((child_cell, level + 1))
            else:
                n_leaf_inputs += 1

        topology_elements.append((level, init, n_leaf_inputs, n_lut_inputs))

    if not topology_elements:
        return hashlib.sha1(b"EMPTY_CONE").hexdigest(), 0

    # Sort for canonical form — BFS visit order varies by dict iteration
    topology_elements.sort()
    digest = hashlib.sha1(repr(topology_elements).encode()).hexdigest()
    return digest, len(topology_elements)


def pass_cone_hashes(bs_id, conn, n_workers, max_depth=6):
    cur = conn.cursor()

    cur.execute("SELECT cell, d FROM ffs WHERE bitstream=%s", (bs_id,))
    all_ffs = cur.fetchall()

    # Which LUT cell produces each net
    cur.execute("SELECT cell, z FROM luts WHERE bitstream=%s AND z IS NOT NULL", (bs_id,))
    lut_driving = {out_z: cell for cell, out_z in cur.fetchall()}

    # LUT topology: cell -> (init, [port_a, port_b, port_c, port_d])
    cur.execute("SELECT cell, init, a, b, c, d FROM luts WHERE bitstream=%s", (bs_id,))
    lut_topology = {cell: (init, [pa, pb, pc, pd])
                    for cell, init, pa, pb, pc, pd in cur.fetchall()}

    cur.execute("DELETE FROM cone_hashes WHERE bitstream=%s", (bs_id,))
    conn.commit()
    cur.close()

    total          = len(all_ffs)
    progress_count = [0]
    lock           = threading.Lock()
    errors         = []

    def process_chunk(ff_chunk):
        try:
            chunk_conn = connect()
            chunk_cur  = chunk_conn.cursor()
            rows = []
            for ff_cell, d_net in ff_chunk:
                cone_hash, cone_size = _topology_hash_for_ff(
                    d_net, lut_driving, lut_topology, max_depth
                )
                rows.append((bs_id, ff_cell, cone_hash, cone_size))
            bulk_insert(chunk_cur, """
                INSERT INTO cone_hashes (bitstream, ff_cell, cone_hash, cone_size)
                VALUES %s ON CONFLICT DO NOTHING
            """, rows)
            chunk_conn.commit()
            chunk_cur.close()
            chunk_conn.close()
            with lock:
                progress_count[0] += len(ff_chunk)
                n = progress_count[0]
                if n % 200 == 0 or n == total:
                    print(f"  cone_hashes {n}/{total}", end="\r", flush=True)
        except Exception as exc:
            with lock:
                errors.append(str(exc))

    chunk_size = max(1, math.ceil(total / n_workers))
    chunks  = [all_ffs[i:i + chunk_size] for i in range(0, total, chunk_size)]
    threads = [threading.Thread(target=process_chunk, args=(chunk,)) for chunk in chunks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if errors:
        die(f"cone_hashes worker failed: {errors[0]}")

    # Read back the count using a fresh connection (chunk connections are closed)
    verify_conn = connect()
    verify_cur  = verify_conn.cursor()
    verify_cur.execute("SELECT count(*) FROM cone_hashes WHERE bitstream=%s", (bs_id,))
    n = verify_cur.fetchone()[0]
    verify_cur.close()
    verify_conn.close()
    return n


# ---------------------------------------------------------------------------
# Pass 8: const_nets — propagate constant values through LUTs
# ---------------------------------------------------------------------------

def _evaluate_lut_init(init_bits, input_values):
    """
    Evaluate a 16-bit LUT init table given four input bit values.

    init_bits is a 16-character binary string, LSB-first:
      index 0 = a=0, b=0, c=0, d=0
      index 1 = a=1, b=0, c=0, d=0
      etc.

    input_values is {'a': '0'/'1', 'b': ..., 'c': ..., 'd': ...}.
    None entries (unconnected port) are treated as '0'.

    Returns '0' or '1'.
    """
    bit_a = int(input_values.get('a') or '0')
    bit_b = int(input_values.get('b') or '0')
    bit_c = int(input_values.get('c') or '0')
    bit_d = int(input_values.get('d') or '0')
    index = bit_a | (bit_b << 1) | (bit_c << 2) | (bit_d << 3)
    if index >= len(init_bits):
        die(f"LUT init index {index} out of range (init={init_bits!r})")
    return init_bits[index]


def pass_const_nets(bs_id, conn):
    """
    Seed constant nets from:
      - LUTs with fn=CONST0 → output net is always '0'
      - LUTs with fn=CONST1 → output net is always '1'
      - FFs with d='1'b0' and no CE (or CE='1'b0') → Q is stuck at '0'

    Then propagate: if ALL inputs to a LUT are const, evaluate the LUT's
    init table to determine its output value, and mark that net const too.
    Repeat until no new const nets are discovered (fixed-point iteration).
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM const_nets WHERE bitstream=%s", (bs_id,))

    const_values = {}   # net_name -> '0' or '1'

    # Seed from CONST LUTs
    cur.execute("""
        SELECT z, fn FROM luts
        WHERE bitstream=%s AND z IS NOT NULL AND fn IN ('CONST0','CONST1')
    """, (bs_id,))
    for out_net, fn in cur.fetchall():
        const_values[out_net] = '0' if fn == 'CONST0' else '1'

    # Seed from permanently-reset FFs
    cur.execute("""
        SELECT q FROM ffs
        WHERE bitstream=%s AND q IS NOT NULL
          AND d = '1''b0'
          AND (ce = '1''b0' OR ce IS NULL)
    """, (bs_id,))
    for (q_net,) in cur.fetchall():
        const_values[q_net] = '0'

    # All LUTs that could propagate const values (exclude CONST LUTs already seeded)
    cur.execute("""
        SELECT cell, init, a, b, c, d, z FROM luts
        WHERE bitstream=%s AND z IS NOT NULL
          AND fn NOT IN ('CONST0','CONST1')
    """, (bs_id,))
    propagation_luts = cur.fetchall()

    # Iterate until no new const nets appear
    made_progress = True
    while made_progress:
        made_progress = False
        for _cell, init, pa, pb, pc, pd, out_net in propagation_luts:
            if out_net in const_values:
                continue   # already determined

            # All four inputs must be known constants (None = unconnected = '0')
            input_vals = {
                'a': const_values.get(pa) if pa else '0',
                'b': const_values.get(pb) if pb else '0',
                'c': const_values.get(pc) if pc else '0',
                'd': const_values.get(pd) if pd else '0',
            }
            if any(v is None for v in input_vals.values()):
                continue   # at least one input is not yet known to be constant

            result = _evaluate_lut_init(init, input_vals)
            const_values[out_net] = result
            made_progress = True

    rows = [(bs_id, net, value) for net, value in const_values.items()]
    bulk_insert(cur, """
        INSERT INTO const_nets (bitstream, net, const_value)
        VALUES %s ON CONFLICT DO NOTHING
    """, rows)
    conn.commit()
    cur.close()
    return len(rows)


# ---------------------------------------------------------------------------
# Main — run all eight passes in order
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--bitstream", default="V07",
                    help="Bitstream label to analyse (default: V07)")
    ap.add_argument("--workers",   type=int, default=24,
                    help="Parallel worker threads for cone_hashes pass (default: 24)")
    ap.add_argument("--depth",     type=int, default=4,
                    help="Max LUT depth for symbolic expansion and cone hashing (default: 4)")
    args = ap.parse_args()

    conn = connect()
    cur  = conn.cursor()
    cur.execute("SELECT id FROM bitstreams WHERE label=%s", (args.bitstream,))
    row = cur.fetchone()
    if not row:
        die(f"Bitstream {args.bitstream!r} not found — run load.py first")
    bs_id = row[0]
    cur.close()

    create_new_tables(conn)
    conn.close()

    wall_start = time.time()
    timings    = []

    def run_pass(label, fn):
        """Open a fresh connection, run fn(conn, ...), close, record timing."""
        print(f"{label}…", flush=True)
        t      = time.time()
        c      = connect()
        result = fn(c)
        c.close()
        elapsed = time.time() - t
        timings.append((label, elapsed))
        return result, elapsed

    # Pass 1 — LUT symbolic expansion
    n, elapsed = run_pass(
        "Pass 1: LUT symbolic expansion",
        lambda c: pass_lut_symbolic(bs_id, c, args.depth)
    )
    print(f"  {n} LUT expressions  ({elapsed:.2f}s)")

    # Pass 2 — FF D-input functions
    n, elapsed = run_pass(
        "Pass 2: FF D-input functions",
        lambda c: pass_ff_d_functions(bs_id, c)
    )
    print(f"  {n} FF functions  ({elapsed:.2f}s)")

    # Pass 3 — shift register detection
    result, elapsed = run_pass(
        "Pass 3: shift register detection",
        lambda c: pass_shift_registers(bs_id, c)
    )
    n_chains, n_bits = result
    print(f"  {n_chains} chains, {n_bits} total FFs  ({elapsed:.2f}s)")

    # Pass 4 — clock domain crossings (pure SQL)
    n, elapsed = run_pass(
        "Pass 4: clock domain crossings",
        lambda c: pass_clock_crossings(bs_id, c)
    )
    print(f"  {n} crossings  ({elapsed:.2f}s)")

    # Pass 5 — EBR bus classification
    n, elapsed = run_pass(
        "Pass 5: EBR bus classification",
        lambda c: pass_ebr_buses(bs_id, c)
    )
    print(f"  {n} bus port assignments  ({elapsed:.2f}s)")

    # Pass 6 — net fan-in/fan-out statistics
    n, elapsed = run_pass(
        "Pass 6: net fan-in / fan-out statistics",
        lambda c: pass_net_stats(bs_id, c)
    )
    print(f"  {n} nets  ({elapsed:.2f}s)")

    # Pass 7 — cone hashes (parallelised internally; doesn't fit the run_pass pattern)
    print("Pass 7: FF input cone structural hashes…", flush=True)
    t = time.time()
    n = pass_cone_hashes(bs_id, connect(), args.workers, max_depth=args.depth)
    elapsed = time.time() - t
    timings.append(("Pass 7: cone_hashes", elapsed))
    print(f"\n  {n} cone hashes  ({elapsed:.2f}s)")

    # Report which cone structures appear most often (structurally identical sub-circuits)
    summary_conn = connect()
    summary_cur  = summary_conn.cursor()
    summary_cur.execute("""
        SELECT cone_hash, count(*) AS n_ffs, min(cone_size) AS depth
        FROM cone_hashes WHERE bitstream=%s
        GROUP BY cone_hash HAVING count(*) > 1
        ORDER BY n_ffs DESC LIMIT 5
    """, (bs_id,))
    duplicates = summary_cur.fetchall()
    summary_cur.close()
    summary_conn.close()
    if duplicates:
        print("  Most-duplicated cone structures (identical topology, different nets):")
        for cone_hash, n_ffs, depth in duplicates:
            print(f"    {cone_hash[:12]}…  {n_ffs} FFs  depth={depth}")

    # Pass 8 — constant net propagation
    n, elapsed = run_pass(
        "Pass 8: constant net propagation",
        lambda c: pass_const_nets(bs_id, c)
    )
    print(f"  {n} constant nets  ({elapsed:.2f}s)")

    # Summary bar chart
    total_elapsed = time.time() - wall_start
    print(f"\n══ reach3 complete  ({total_elapsed:.2f}s) ══")
    print("  Stage timings:")
    for pass_name, t_pass in timings:
        bar = "█" * max(1, round(t_pass / total_elapsed * 30))
        print(f"  {pass_name:<42}  {t_pass:5.2f}s  {bar}")


if __name__ == "__main__":
    main()
