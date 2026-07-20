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
import schema
from db import engine, die, BACKEND
from sqlalchemy import select, insert, delete, update, func, and_, or_, text


# ---------------------------------------------------------------------------
# ON CONFLICT helper
# ---------------------------------------------------------------------------

def _insert_ignore(table):
    """Return an INSERT that silently ignores duplicate-key conflicts on both backends."""
    if BACKEND == "sqlite":
        return insert(table).prefix_with("OR IGNORE")
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    return pg_insert(table).on_conflict_do_nothing()


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


def pass_lut_symbolic(bs_id, max_depth):
    t  = schema.luts
    ls = schema.lut_symbolic

    with engine().begin() as conn:
        rows = conn.execute(
            select(t.c.cell, t.c.fn, t.c.a, t.c.b, t.c.c, t.c.d, t.c.z, t.c.init)
            .where(t.c.bitstream == bs_id)
        ).fetchall()

    if not rows:
        die(f"No LUTs for bitstream {bs_id} — was load.py run?")

    lut_rows = [(r.cell, r.fn, r.a, r.b, r.c, r.d, r.z, r.init) for r in rows]
    expanded = _expand_lut_expressions(lut_rows, max_depth)

    insert_rows = [
        {"bitstream": bs_id, "lut_cell": cell, "expr": expr, "depth": depth}
        for cell, (expr, depth) in expanded.items()
    ]

    with engine().begin() as conn:
        conn.execute(delete(ls).where(ls.c.bitstream == bs_id))
        if insert_rows:
            conn.execute(_insert_ignore(ls), insert_rows)

    return len(insert_rows)


# ---------------------------------------------------------------------------
# Pass 2: ff_d_functions — symbolic D-input expression per FF
# ---------------------------------------------------------------------------

def pass_ff_d_functions(bs_id):
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
    ffd   = schema.ff_d_functions
    t_ffs = schema.ffs
    t_ls  = schema.lut_symbolic
    t_lut = schema.luts
    t_pad = schema.pad_map
    t_pfi = schema.pad_ff_influence

    with engine().begin() as conn:
        # Load FFs
        all_ffs = conn.execute(
            select(t_ffs.c.cell, t_ffs.c.d, t_ffs.c.ce)
            .where(t_ffs.c.bitstream == bs_id)
        ).fetchall()

        # Load symbolic expressions from pass 1
        sym_rows = conn.execute(
            select(t_ls.c.lut_cell, t_ls.c.expr, t_ls.c.depth)
            .where(t_ls.c.bitstream == bs_id)
        ).fetchall()
        symbolic_by_lut = {r.lut_cell: (r.expr, r.depth) for r in sym_rows}

        # Which LUT cell produces each net
        lut_z_rows = conn.execute(
            select(t_lut.c.cell, t_lut.c.z)
            .where(and_(t_lut.c.bitstream == bs_id, t_lut.c.z != None))
        ).fetchall()
        lut_driving = {r.z: r.cell for r in lut_z_rows}

        # Pad label by the net that comes in from that pad
        pad_rows = conn.execute(
            select(t_pad.c.net_in, t_pad.c.label)
            .where(and_(t_pad.c.bitstream == bs_id, t_pad.c.net_in != None))
        ).fetchall()
        pad_label_by_net = {r.net_in: r.label for r in pad_rows}

        # Which pads transitively reach each FF (from pad_ff_influence)
        pfi_rows = conn.execute(
            select(t_pfi.c.ff_cell, t_pfi.c.pad_label)
            .where(t_pfi.c.bitstream == bs_id)
            .order_by(t_pfi.c.ff_cell, t_pfi.c.pad_label)
        ).fetchall()
        pad_inputs_by_ff = {}
        for r in pfi_rows:
            pad_inputs_by_ff.setdefault(r.ff_cell, []).append(r.pad_label)

        conn.execute(delete(ffd).where(ffd.c.bitstream == bs_id))

        output_rows = []
        for ff_row in all_ffs:
            ff_cell = ff_row.cell
            d_net   = ff_row.d

            if d_net is None or d_net == "1'b0":
                fn_expr    = '0'
                expr_depth = 0
            elif d_net == "1'b1":
                fn_expr    = '1'
                expr_depth = 0
            elif d_net in lut_driving:
                driving_lut         = lut_driving[d_net]
                fn_expr, expr_depth = symbolic_by_lut.get(driving_lut, (d_net, 0))
            elif d_net in pad_label_by_net:
                fn_expr    = pad_label_by_net[d_net]
                expr_depth = 0
            else:
                fn_expr    = d_net   # raw net name (another FF's Q or unresolved)
                expr_depth = 0

            pad_inputs = pad_inputs_by_ff.get(ff_cell)
            output_rows.append({
                "bitstream":  bs_id,
                "ff_cell":    ff_cell,
                "fn_expr":    fn_expr,
                "depth":      expr_depth,
                "pad_inputs": pad_inputs,
            })

        if output_rows:
            conn.execute(_insert_ignore(ffd), output_rows)

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


def _build_ff_q_to_d_edges(ff_rows, buf_shortcuts, lut_rows=None):
    """
    Return {src_ff_cell: (dst_ff_cell, dst_clk, dst_ce, via_buf)} for every
    FF whose Q net feeds directly (or via one BUF LUT or AND-gating LUT) into
    another FF's D.

    ff_rows: list of (cell, clk, ce, d, q)
    lut_rows: list of (cell, fn, a, b, c, d, z) for gated-shift detection

    Issue #77: Extended to recognize gated shift chains where a LUT computes
    (Q_prev & enable) between FF stages. This is used in SPI/command registers.
    """
    ff_by_q_net = {}   # q_net -> (cell, clk, ce)
    ff_by_d_net = {}   # d_net -> (cell, clk, ce)

    for cell, clk, ce, d_net, q_net in ff_rows:
        if q_net and not q_net.startswith("1'b"):
            ff_by_q_net[q_net] = (cell, clk, ce)
        if d_net and not d_net.startswith("1'b"):
            ff_by_d_net[d_net] = (cell, clk, ce)

    # Build gated-shift LUT map if lut_rows provided
    gated_shifts = {}
    if lut_rows:
        for _cell, fn, pa, pb, pc, pd, out_z in lut_rows:
            if not (fn and out_z):
                continue
            # Recognize AND functions: fn='AND(a,b)' or similar 2-input AND patterns
            if "AND(" in fn:
                match = re.match(r'AND\(([abcd]),([abcd])\)', fn)
                if match:
                    port1, port2 = match.group(1), match.group(2)
                    net_map = {'a': pa, 'b': pb, 'c': pc, 'd': pd}
                    net1 = net_map.get(port1)
                    net2 = net_map.get(port2)
                    if net1 and net2:
                        # Both inputs connected; this is a gating LUT
                        gated_shifts[out_z] = (net1, net2)

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
        elif q_net in gated_shifts:
            # Q → AND_LUT → D connection (gated shift stage)
            # The AND LUT output may feed into the next FF's D directly
            lut_output = None
            for out_z, (net1, net2) in gated_shifts.items():
                if net1 == q_net or net2 == q_net:
                    lut_output = out_z
                    break
            if lut_output and lut_output in ff_by_d_net:
                dst_cell, dst_clk, dst_ce = ff_by_d_net[lut_output]
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


def pass_shift_registers(bs_id):
    t_ffs  = schema.ffs
    t_luts = schema.luts
    t_pat  = schema.patterns
    t_srb  = schema.shift_reg_bits

    with engine().begin() as conn:
        ff_rows_raw = conn.execute(
            select(t_ffs.c.cell, t_ffs.c.clk, t_ffs.c.ce, t_ffs.c.d, t_ffs.c.q)
            .where(t_ffs.c.bitstream == bs_id)
        ).fetchall()

        lut_rows_raw = conn.execute(
            select(t_luts.c.cell, t_luts.c.fn,
                   t_luts.c.a, t_luts.c.b, t_luts.c.c, t_luts.c.d, t_luts.c.z)
            .where(t_luts.c.bitstream == bs_id)
        ).fetchall()

    ff_rows  = [(r.cell, r.clk, r.ce, r.d, r.q) for r in ff_rows_raw]
    lut_rows = [(r.cell, r.fn, r.a, r.b, r.c, r.d, r.z) for r in lut_rows_raw]

    # Build the indexes needed for chain detection
    ff_by_q_net  = {}
    ff_q_by_cell = {}   # ff_cell -> q_net  (for writing shift_reg_bits)
    for cell, clk, ce, d_net, q_net in ff_rows:
        if q_net and not q_net.startswith("1'b"):
            ff_by_q_net[q_net] = (cell, clk, ce)
        if q_net:
            ff_q_by_cell[cell] = q_net

    buf_shortcuts = _find_buf_lut_shortcuts(lut_rows)
    edges         = _build_ff_q_to_d_edges(ff_rows, buf_shortcuts, lut_rows)
    chains        = _walk_ff_chains(edges, ff_by_q_net)

    # Remove old shift-register patterns for this bitstream before writing new ones
    with engine().begin() as conn:
        conn.execute(
            delete(t_pat).where(
                and_(t_pat.c.bitstream == bs_id,
                     t_pat.c.pattern_type == 'shift_reg')
            )
        )

    n_chains     = 0
    n_total_bits = 0

    for chain_cells, clk_net, ce_net in chains:
        label  = f"shift_reg_{n_chains}"
        detail = {
            "length":  len(chain_cells),
            "clk_net": clk_net,
            "ce_net":  ce_net,
            "head_ff": chain_cells[0],
            "tail_ff": chain_cells[-1],
        }

        with engine().begin() as conn:
            result = conn.execute(
                insert(t_pat).values(
                    bitstream=bs_id,
                    pattern_type='shift_reg',
                    label=label,
                    detail=detail,
                ).returning(t_pat.c.id)
            )
            pattern_id = result.fetchone()[0]

            bit_rows = [
                {
                    "pattern_id":  pattern_id,
                    "bit_index":   bit_index,
                    "ff_cell":     ff_cell,
                    "q_net":       ff_q_by_cell.get(ff_cell, ''),
                    "clk_net":     clk_net,
                    "load_en_net": ce_net,
                }
                for bit_index, ff_cell in enumerate(chain_cells)
            ]
            conn.execute(insert(t_srb), bit_rows)

        n_chains     += 1
        n_total_bits += len(chain_cells)

    return n_chains, n_total_bits


# ---------------------------------------------------------------------------
# Pass 4: clock_crossings — FFs whose input cone contains a different-domain FF
# ---------------------------------------------------------------------------

def pass_clock_crossings(bs_id):
    """
    Pure SQL: find every (src_ff, dst_ff) pair where:
      - src_ff.Q appears in dst_ff's input cone (ff_cones.cone_type='input')
      - src_ff and dst_ff are on different clock nets

    These are potential metastability hazards — signals crossing clock domains
    without a synchroniser.
    """
    t_cc  = schema.clock_crossings
    t_fc  = schema.ff_cones
    t_ffs = schema.ffs
    t_cd  = schema.clock_domains

    with engine().begin() as conn:
        conn.execute(delete(t_cc).where(t_cc.c.bitstream == bs_id))

        src_ff = t_ffs.alias("src_ff")
        cd_dst = t_cd.alias("cd_dst")
        cd_src = t_cd.alias("cd_src")

        subq = (
            select(
                t_fc.c.bitstream,
                t_fc.c.ff_cell.label("dst_ff"),
                cd_dst.c.clk_net.label("dst_clk"),
                src_ff.c.cell.label("src_ff"),
                cd_src.c.clk_net.label("src_clk"),
                t_fc.c.min_hops.label("hops"),
            )
            .join(src_ff,
                  and_(src_ff.c.bitstream == t_fc.c.bitstream,
                       src_ff.c.q == t_fc.c.net))
            .join(cd_dst,
                  and_(cd_dst.c.bitstream == t_fc.c.bitstream,
                       cd_dst.c.ff_cell == t_fc.c.ff_cell))
            .join(cd_src,
                  and_(cd_src.c.bitstream == t_fc.c.bitstream,
                       cd_src.c.ff_cell == src_ff.c.cell))
            .where(
                and_(
                    t_fc.c.bitstream == bs_id,
                    t_fc.c.cone_type == 'input',
                    cd_src.c.clk_net != cd_dst.c.clk_net,
                )
            )
        )

        stmt = insert(t_cc).from_select(
            ["bitstream", "dst_ff", "dst_clk", "src_ff", "src_clk", "hops"],
            subq,
        )

        if BACKEND == "sqlite":
            stmt = stmt.prefix_with("OR IGNORE")
        else:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(t_cc).from_select(
                ["bitstream", "dst_ff", "dst_clk", "src_ff", "src_clk", "hops"],
                subq,
            ).on_conflict_do_update(
                index_elements=["bitstream", "dst_ff", "src_ff"],
                set_={"hops": text("excluded.hops")},
            )

        result = conn.execute(stmt)
        return result.rowcount


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


# --- GOWIN GW1N BSRAM port names (issue #69) --------------------------------
# The BSRAM site exposes THREE views of the same physical wires: an unsuffixed
# set (single-port / SDP modes) and A-/B-suffixed sets (true dual-port).  Which
# view is live depends on the configured mode, and all three are recorded in
# ebr_ports — so bit_index carries a per-view offset to satisfy
# UNIQUE(bitstream, block, bus_role, bit_index):
#
#     A-side  +0     B-side  +64     unsuffixed (single-port)  +128
#
# NOTE on addressing: a GW1N BSRAM port has ONE address bus (ADA/ADB) shared by
# reads and writes, unlike the MachXO2 split JC/JD.  Calling it 'write_addr' or
# 'read_addr' would assert something untrue, so it gets its own 'addr' role.
_GOWIN_VIEW_OFFSET = {"A": 0, "B": 64, "": 128}
_GOWIN_CTRL_ORDINAL = {"CLK": 0, "CE": 1, "OCE": 2, "WRE": 3, "RESET": 4}
_GOWIN_BSRAM_RE = re.compile(
    r"^(DI|DO|AD|BLKSEL|CLK|CE|OCE|WRE|RESET)([AB]?)(\d*)$")
_GOWIN_BUS_ROLE = {"DI": "write_data", "DO": "read_data", "AD": "addr"}


def _classify_gowin_bsram_port(port_name):
    """(bus_role, bit_index) for a GW1N BSRAM port, or None."""
    m = _GOWIN_BSRAM_RE.match(port_name)
    if not m:
        return None
    stem, view, bit = m.group(1), m.group(2), m.group(3)
    offset = _GOWIN_VIEW_OFFSET[view]
    role = _GOWIN_BUS_ROLE.get(stem)
    if role is not None:
        # vector bus: bit index must be present
        if bit == "":
            return None
        return role, offset + int(bit)
    if stem == "BLKSEL":
        # block-select is a 3-bit ctrl vector; park it above the scalar ctrls
        return "ctrl", offset + 8 + int(bit or 0)
    return "ctrl", offset + _GOWIN_CTRL_ORDINAL[stem]


def _classify_ebr_port(port_name):
    """
    Return (bus_role, bit_index) for a port like "JA3" / "JE1" (MachXO2) or
    "DIA0" / "CLKB" (GOWIN BSRAM), or None if neither pattern matches.

    MachXO2 ctrl ports (E/F/G/H) get a compound bit_index =
    (letter_offset * 32) + bit so they don't collide with each other.
    """
    match = _EBR_PORT_PATTERN.match(port_name)
    if not match:
        return _classify_gowin_bsram_port(port_name)
    letter    = match.group(1).upper()
    bit_index = int(match.group(2))
    role      = _EBR_LETTER_TO_ROLE.get(letter)
    if role is None:
        return None
    if role == 'ctrl':
        letter_offset = ord(letter) - ord('E')
        bit_index     = letter_offset * 32 + bit_index
    return (role, bit_index)


def pass_ebr_buses(bs_id):
    t_ep = schema.ebr_ports
    t_eb = schema.ebr_buses

    with engine().begin() as conn:
        conn.execute(delete(t_eb).where(t_eb.c.bitstream == bs_id))

        ebr_port_rows = conn.execute(
            select(t_ep.c.block, t_ep.c.port, t_ep.c.net)
            .where(t_ep.c.bitstream == bs_id)
        ).fetchall()

        output_rows = []
        skipped     = 0
        for r in ebr_port_rows:
            classified = _classify_ebr_port(r.port)
            if classified is None:
                skipped += 1
                continue
            role, bit_index = classified
            output_rows.append({
                "bitstream": bs_id,
                "block":     r.block,
                "bus_role":  role,
                "bit_index": bit_index,
                "port":      r.port,
                "net":       r.net,
            })

        if output_rows:
            conn.execute(_insert_ignore(t_eb), output_rows)

    if skipped:
        print(f"  ({skipped} EBR ports skipped — unrecognised name format)", flush=True)
    return len(output_rows)


# ---------------------------------------------------------------------------
# Pass 6: net_stats — fan-in, fan-out, and flag bits for every net
# ---------------------------------------------------------------------------

def pass_net_stats(bs_id):
    """
    For every net in the design, record:
      fanout      — how many cell inputs it drives
      fanin       — how many cells produce it (normally 0 or 1)
      is_clock    — it is the CLK net for at least one FF
      is_const    — it is driven by a constant source (CONST0/CONST1 LUT or stuck FF)
      is_boundary — it connects to a physical pad or an EFB port
    """
    t_ns  = schema.net_stats
    t_nf  = schema.net_fanout
    t_cd  = schema.clock_domains
    t_lut = schema.luts
    t_ffs = schema.ffs
    t_pad = schema.pad_map
    t_efb = schema.efb_ports
    t_net = schema.nets

    with engine().begin() as conn:
        conn.execute(delete(t_ns).where(t_ns.c.bitstream == bs_id))

        # Fan-out: count how many cell inputs are driven by each net
        fanout_rows = conn.execute(
            select(t_nf.c.net, func.count().label("cnt"))
            .where(t_nf.c.bitstream == bs_id)
            .group_by(t_nf.c.net)
        ).fetchall()
        fanout_by_net = {r.net: r.cnt for r in fanout_rows}

        # Fan-in: count how many cells produce each net
        fanin_rows = conn.execute(
            select(t_nf.c.out_net, func.count().label("cnt"))
            .where(and_(t_nf.c.bitstream == bs_id, t_nf.c.out_net != None))
            .group_by(t_nf.c.out_net)
        ).fetchall()
        fanin_by_net = {r.out_net: r.cnt for r in fanin_rows}

        # Clock nets: appear as clk_net in clock_domains
        clock_rows = conn.execute(
            select(t_cd.c.clk_net).distinct()
            .where(t_cd.c.bitstream == bs_id)
        ).fetchall()
        clock_nets = {r.clk_net for r in clock_rows}

        # Const nets from LUTs with constant output
        const_lut_rows = conn.execute(
            select(t_lut.c.z)
            .where(and_(
                t_lut.c.bitstream == bs_id,
                t_lut.c.z != None,
                t_lut.c.fn.in_(('CONST0', 'CONST1')),
            ))
        ).fetchall()
        const_nets = {r.z for r in const_lut_rows}

        # Also: FFs stuck at reset — d='1'b0' with no CE (or CE='1'b0') → Q is const 0
        stuck_ff_rows = conn.execute(
            select(t_ffs.c.q)
            .where(and_(
                t_ffs.c.bitstream == bs_id,
                t_ffs.c.q != None,
                t_ffs.c.d == "1'b0",
                or_(t_ffs.c.ce == "1'b0", t_ffs.c.ce == None),
            ))
        ).fetchall()
        for r in stuck_ff_rows:
            const_nets.add(r.q)

        # Boundary nets: physical pad nets + EFB port nets
        pad_in_rows = conn.execute(
            select(t_pad.c.net_in)
            .where(and_(t_pad.c.bitstream == bs_id, t_pad.c.net_in != None))
        ).fetchall()
        pad_out_rows = conn.execute(
            select(t_pad.c.net_out)
            .where(and_(t_pad.c.bitstream == bs_id, t_pad.c.net_out != None))
        ).fetchall()
        efb_rows = conn.execute(
            select(t_efb.c.net)
            .where(and_(t_efb.c.bitstream == bs_id, t_efb.c.net != None))
        ).fetchall()
        boundary_nets = (
            {r.net_in  for r in pad_in_rows}
            | {r.net_out for r in pad_out_rows}
            | {r.net    for r in efb_rows}
        )

        # All nets in the design
        all_net_rows = conn.execute(
            select(t_net.c.name).where(t_net.c.bitstream == bs_id)
        ).fetchall()
        all_net_names = [r.name for r in all_net_rows]

        output_rows = [
            {
                "bitstream":   bs_id,
                "net":         net,
                "fanout":      fanout_by_net.get(net, 0),
                "fanin":       fanin_by_net.get(net, 0),
                "is_clock":    net in clock_nets,
                "is_const":    net in const_nets,
                "is_boundary": net in boundary_nets,
            }
            for net in all_net_names
        ]

        if output_rows:
            conn.execute(_insert_ignore(t_ns), output_rows)

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


def pass_cone_hashes(bs_id, n_workers, max_depth=6):
    t_ffs  = schema.ffs
    t_luts = schema.luts
    t_ch   = schema.cone_hashes

    with engine().begin() as conn:
        all_ffs_raw = conn.execute(
            select(t_ffs.c.cell, t_ffs.c.d)
            .where(t_ffs.c.bitstream == bs_id)
        ).fetchall()
        all_ffs = [(r.cell, r.d) for r in all_ffs_raw]

        # Which LUT cell produces each net
        lut_z_rows = conn.execute(
            select(t_luts.c.cell, t_luts.c.z)
            .where(and_(t_luts.c.bitstream == bs_id, t_luts.c.z != None))
        ).fetchall()
        lut_driving = {r.z: r.cell for r in lut_z_rows}

        # LUT topology: cell -> (init, [port_a, port_b, port_c, port_d])
        lut_topo_rows = conn.execute(
            select(t_luts.c.cell, t_luts.c.init,
                   t_luts.c.a, t_luts.c.b, t_luts.c.c, t_luts.c.d)
            .where(t_luts.c.bitstream == bs_id)
        ).fetchall()
        lut_topology = {r.cell: (r.init, [r.a, r.b, r.c, r.d])
                        for r in lut_topo_rows}

        conn.execute(delete(t_ch).where(t_ch.c.bitstream == bs_id))

    total          = len(all_ffs)
    progress_count = [0]
    lock           = threading.Lock()
    # Serialise inserts: concurrent whole-chunk transactions exhaust the
    # SQLAlchemy pool (5+10, 30s) and SQLite single-writes anyway.
    insert_lock    = threading.Lock()
    errors         = []

    def process_chunk(ff_chunk):
        try:
            rows = []
            for ff_cell, d_net in ff_chunk:
                cone_hash, cone_size = _topology_hash_for_ff(
                    d_net, lut_driving, lut_topology, max_depth
                )
                rows.append({
                    "bitstream": bs_id,
                    "ff_cell":   ff_cell,
                    "cone_hash": cone_hash,
                    "cone_size": cone_size,
                })
            with insert_lock:
                with engine().begin() as chunk_conn:
                    chunk_conn.execute(_insert_ignore(t_ch), rows)
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

    # Read back the count
    with engine().begin() as conn:
        n = conn.execute(
            select(func.count()).select_from(t_ch)
            .where(t_ch.c.bitstream == bs_id)
        ).scalar()
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


def pass_const_nets(bs_id):
    """
    Seed constant nets from:
      - LUTs with fn=CONST0 → output net is always '0'
      - LUTs with fn=CONST1 → output net is always '1'
      - FFs with d='1'b0' and no CE (or CE='1'b0') → Q is stuck at '0'

    Then propagate: if ALL inputs to a LUT are const, evaluate the LUT's
    init table to determine its output value, and mark that net const too.
    Repeat until no new const nets are discovered (fixed-point iteration).
    """
    t_cn  = schema.const_nets
    t_lut = schema.luts
    t_ffs = schema.ffs

    with engine().begin() as conn:
        conn.execute(delete(t_cn).where(t_cn.c.bitstream == bs_id))

        const_values = {}   # net_name -> '0' or '1'

        # Seed from CONST LUTs
        const_lut_rows = conn.execute(
            select(t_lut.c.z, t_lut.c.fn)
            .where(and_(
                t_lut.c.bitstream == bs_id,
                t_lut.c.z != None,
                t_lut.c.fn.in_(('CONST0', 'CONST1')),
            ))
        ).fetchall()
        for r in const_lut_rows:
            const_values[r.z] = '0' if r.fn == 'CONST0' else '1'

        # Seed from permanently-reset FFs
        stuck_rows = conn.execute(
            select(t_ffs.c.q)
            .where(and_(
                t_ffs.c.bitstream == bs_id,
                t_ffs.c.q != None,
                t_ffs.c.d == "1'b0",
                or_(t_ffs.c.ce == "1'b0", t_ffs.c.ce == None),
            ))
        ).fetchall()
        for r in stuck_rows:
            const_values[r.q] = '0'

        # All LUTs that could propagate const values (exclude CONST LUTs already seeded)
        prop_rows = conn.execute(
            select(t_lut.c.cell, t_lut.c.init,
                   t_lut.c.a, t_lut.c.b, t_lut.c.c, t_lut.c.d, t_lut.c.z)
            .where(and_(
                t_lut.c.bitstream == bs_id,
                t_lut.c.z != None,
                t_lut.c.fn.not_in(('CONST0', 'CONST1')),
            ))
        ).fetchall()
        propagation_luts = [(r.cell, r.init, r.a, r.b, r.c, r.d, r.z)
                            for r in prop_rows]

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

        rows = [{"bitstream": bs_id, "net": net, "const_value": value}
                for net, value in const_values.items()]
        if rows:
            conn.execute(_insert_ignore(t_cn), rows)

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

    t_bs = schema.bitstreams
    with engine().begin() as conn:
        row = conn.execute(
            select(t_bs.c.id).where(t_bs.c.label == args.bitstream)
        ).fetchone()
        if not row:
            die(f"Bitstream {args.bitstream!r} not found — run load.py first")
        bs_id = row[0]

    # schema.init() is called by load.py before reach3 runs; tables already exist.

    wall_start = time.time()
    timings    = []

    def run_pass(label, fn):
        """Run fn(), record timing."""
        print(f"{label}…", flush=True)
        t      = time.time()
        result = fn()
        elapsed = time.time() - t
        timings.append((label, elapsed))
        return result, elapsed

    # Pass 1 — LUT symbolic expansion
    n, elapsed = run_pass(
        "Pass 1: LUT symbolic expansion",
        lambda: pass_lut_symbolic(bs_id, args.depth)
    )
    print(f"  {n} LUT expressions  ({elapsed:.2f}s)")

    # Pass 2 — FF D-input functions
    n, elapsed = run_pass(
        "Pass 2: FF D-input functions",
        lambda: pass_ff_d_functions(bs_id)
    )
    print(f"  {n} FF functions  ({elapsed:.2f}s)")

    # Pass 3 — shift register detection
    result, elapsed = run_pass(
        "Pass 3: shift register detection",
        lambda: pass_shift_registers(bs_id)
    )
    n_chains, n_bits = result
    print(f"  {n_chains} chains, {n_bits} total FFs  ({elapsed:.2f}s)")

    # Pass 4 — clock domain crossings (pure SQL)
    n, elapsed = run_pass(
        "Pass 4: clock domain crossings",
        lambda: pass_clock_crossings(bs_id)
    )
    print(f"  {n} crossings  ({elapsed:.2f}s)")

    # Pass 5 — EBR bus classification
    n, elapsed = run_pass(
        "Pass 5: EBR bus classification",
        lambda: pass_ebr_buses(bs_id)
    )
    print(f"  {n} bus port assignments  ({elapsed:.2f}s)")

    # Pass 6 — net fan-in/fan-out statistics
    n, elapsed = run_pass(
        "Pass 6: net fan-in / fan-out statistics",
        lambda: pass_net_stats(bs_id)
    )
    print(f"  {n} nets  ({elapsed:.2f}s)")

    # Pass 7 — cone hashes (parallelised internally; doesn't fit the run_pass pattern)
    print("Pass 7: FF input cone structural hashes…", flush=True)
    t = time.time()
    n = pass_cone_hashes(bs_id, args.workers, max_depth=args.depth)
    elapsed = time.time() - t
    timings.append(("Pass 7: cone_hashes", elapsed))
    print(f"\n  {n} cone hashes  ({elapsed:.2f}s)")

    # Report which cone structures appear most often (structurally identical sub-circuits)
    t_ch = schema.cone_hashes
    with engine().begin() as conn:
        duplicates = conn.execute(
            select(
                t_ch.c.cone_hash,
                func.count().label("n_ffs"),
                func.min(t_ch.c.cone_size).label("depth"),
            )
            .where(t_ch.c.bitstream == bs_id)
            .group_by(t_ch.c.cone_hash)
            .having(func.count() > 1)
            .order_by(func.count().desc())
            .limit(5)
        ).fetchall()
    if duplicates:
        print("  Most-duplicated cone structures (identical topology, different nets):")
        for row in duplicates:
            print(f"    {row.cone_hash[:12]}…  {row.n_ffs} FFs  depth={row.depth}")

    # Pass 8 — constant net propagation
    n, elapsed = run_pass(
        "Pass 8: constant net propagation",
        lambda: pass_const_nets(bs_id)
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
