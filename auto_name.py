#!/usr/bin/env python3
"""Pluribus — automatic net naming from structural patterns.

Runs after reach3.py (lut_symbolic populated) and before verilog.py.
Inserts net_names rows with source='auto' so load.py can distinguish
auto-inferred names from hand-curated TSV names.

Naming rules (applied in priority order, first match wins):
  1. Init-pattern rules: specific 16-bit LUT init strings → structural roles
     (DDR deserialiser, Gray comparator, carry chain, AND4, OR4, …)
  2. Expression-derivation rules: LUTs whose expression uses only already-named
     nets → derive output name from expression
     (INV(spi_ctrl) → spi_ctrl_n, BUF(ebr_wclk) → ebr_wclk,
      AND(a,b) → a_and_b, XOR(a,b) → a_xor_b, …)

All auto-names use confidence='inferred'. Hand-curated TSV names (loaded by
load.py) always take priority: ON CONFLICT DO NOTHING preserves them.

Iterates to convergence: each pass may name nets whose expressions were
previously opaque because their inputs were unnamed.  Stops when no new names
are produced in a pass.

Usage:
    python3 fpga/pluribus/auto_name.py [--bitstream V07]
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import connect, die

# ---------------------------------------------------------------------------
# Init-pattern rules
# Format: init_str → (name_fn, type, confidence, note_template)
# name_fn(row, col, slice_, k) → str
# note_template: %PORTS% replaced by rendered "a=name b=name" string
# ---------------------------------------------------------------------------

def _pos_name(prefix, row, col, sl, k):
    return f"{prefix}_r{row}c{col}_{sl}k{k}"


INIT_RULES = {
    "0111100010001000": (
        lambda r, c, s, k: _pos_name("ddr_mux",  r, c, s, k),
        "data", "inferred",
        "AI init-rule: DDR 2:1 mux (INIT=0111100010001000). "
        "Selects between two half-cycle data sources based on ENCB phase. "
        "Ports: %PORTS%"
    ),
    "1000001001000001": (
        lambda r, c, s, k: _pos_name("gray_cmp", r, c, s, k),
        "ctrl", "inferred",
        "AI init-rule: Gray-code comparator (INIT=1000001001000001). "
        "True when XNOR(a,b) & XNOR(c,d). Ports: %PORTS%"
    ),
    "1000010000100001": (
        lambda r, c, s, k: _pos_name("gray_cmp", r, c, s, k),
        "ctrl", "inferred",
        "AI init-rule: 2-bit equality (INIT=1000010000100001). "
        "True when (a==b) & (c==d). Ports: %PORTS%"
    ),
    "1000000000000000": (
        lambda r, c, s, k: _pos_name("and4",     r, c, s, k),
        "ctrl", "inferred",
        "AI init-rule: 4-input AND (INIT=1000000000000000). Ports: %PORTS%"
    ),
    "1111111111111110": (
        lambda r, c, s, k: _pos_name("or4",      r, c, s, k),
        "ctrl", "inferred",
        "AI init-rule: 4-input OR (INIT=1111111111111110). Ports: %PORTS%"
    ),
    "0011100110011001": (
        lambda r, c, s, k: _pos_name("carry",    r, c, s, k),
        "ctrl", "inferred",
        "AI init-rule: carry/adder cell (INIT=0011100110011001). Ports: %PORTS%"
    ),
    "0101100110011001": (
        lambda r, c, s, k: _pos_name("carry",    r, c, s, k),
        "ctrl", "inferred",
        "AI init-rule: carry/adder cell (INIT=0101100110011001). Ports: %PORTS%"
    ),
    "0011011001100110": (
        lambda r, c, s, k: _pos_name("carry",    r, c, s, k),
        "ctrl", "inferred",
        "AI init-rule: carry/adder variant (INIT=0011011001100110). Ports: %PORTS%"
    ),
    "0110011001100110": (
        lambda r, c, s, k: _pos_name("xor4",     r, c, s, k),
        "ctrl", "inferred",
        "AI init-rule: 4-input XOR/parity (INIT=0110011001100110). Ports: %PORTS%"
    ),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NET_N = re.compile(r'^n\d+$')
_CELL  = re.compile(r'^lut_r(\d+)c(\d+)_([A-D])k([01])$')


def _is_raw(net):
    return net and bool(_NET_N.match(net))


def _short(name, max_len=14):
    if not name or len(name) <= max_len:
        return name or ''
    for pfx in ('clk_', 'reg_', 'ebr_', 'spi_', 'adc_', 'dac_', 'awg_'):
        if name.startswith(pfx):
            return name[len(pfx):][:max_len]
    return name[:max_len]


def _sanitise(name):
    name = re.sub(r'[^a-z0-9_]', '_', (name or '').lower())
    name = re.sub(r'_+', '_', name).strip('_')
    return name[:48] or 'unnamed'


def _plist(ports):
    return ' '.join(f"{k}={v}" for k, v in sorted(ports.items()) if v)


def _all_named(ports):
    return all(not _is_raw(v) for v in ports.values() if v)


# ---------------------------------------------------------------------------
# Expression-derivation rules
# Each rule: (match_fn, name_fn, note_fn)
# match_fn(expr, ports) → bool
# name_fn(expr, ports) → str
# note_fn(expr) → str
# ---------------------------------------------------------------------------

_PAT_BUF   = re.compile(r'^[a-z][a-z0-9_\[\]]+$')
_PAT_INV   = re.compile(r'^!([a-z][a-z0-9_\[\]]+)$')
_PAT_AND2  = re.compile(r'^([a-z][a-z0-9_\[\]]+) & ([a-z][a-z0-9_\[\]]+)$')
_PAT_OR2   = re.compile(r'^([a-z][a-z0-9_\[\]]+) \| ([a-z][a-z0-9_\[\]]+)$')
_PAT_XOR2  = re.compile(
    r'^\(([a-z][a-z0-9_\[\]]+) & !([a-z][a-z0-9_\[\]]+)\) \| '
    r'\(!([a-z][a-z0-9_\[\]]+) & ([a-z][a-z0-9_\[\]]+)\)$'
)
_PAT_NOR2  = re.compile(r'^!([a-z][a-z0-9_\[\]]+) & !([a-z][a-z0-9_\[\]]+)$')
_PAT_NAND2 = re.compile(r'^!([a-z][a-z0-9_\[\]]+) \| !([a-z][a-z0-9_\[\]]+)$')
_PAT_MUX   = re.compile(
    r'^\(([a-z][a-z0-9_\[\]]+) & ([a-z][a-z0-9_\[\]]+)\) \| '
    r'\(!([a-z][a-z0-9_\[\]]+) & ([a-z][a-z0-9_\[\]]+)\)$'
)


def _xor2_check(e, _p):
    m = _PAT_XOR2.match(e)
    return bool(m) and m.group(1) == m.group(3)


def _mux_check(e, _p):
    m = _PAT_MUX.match(e)
    return bool(m) and m.group(1) == m.group(3)


EXPR_RULES = [
    # BUF: expr is a single named net
    (_PAT_BUF.match,
     lambda e, p: _short(e),
     lambda e: f"AI: buffer/alias of {e}"),

    # INV: !name
    (lambda e, p: bool(_PAT_INV.match(e)),
     lambda e, p: _short(_PAT_INV.match(e).group(1)) + '_n',
     lambda e: f"AI: INV({_PAT_INV.match(e).group(1)})"),

    # AND2
    (lambda e, p: bool(_PAT_AND2.match(e)),
     lambda e, p: (_short(_PAT_AND2.match(e).group(1)) + '_and_'
                   + _short(_PAT_AND2.match(e).group(2))),
     lambda e: f"AI: AND({_PAT_AND2.match(e).group(1)}, {_PAT_AND2.match(e).group(2)})"),

    # OR2
    (lambda e, p: bool(_PAT_OR2.match(e)),
     lambda e, p: (_short(_PAT_OR2.match(e).group(1)) + '_or_'
                   + _short(_PAT_OR2.match(e).group(2))),
     lambda e: f"AI: OR({_PAT_OR2.match(e).group(1)}, {_PAT_OR2.match(e).group(2)})"),

    # XOR2
    (_xor2_check,
     lambda e, p: (_short(_PAT_XOR2.match(e).group(1)) + '_xor_'
                   + _short(_PAT_XOR2.match(e).group(2))),
     lambda e: f"AI: XOR({_PAT_XOR2.match(e).group(1)}, {_PAT_XOR2.match(e).group(2)})"),

    # NOR2
    (lambda e, p: bool(_PAT_NOR2.match(e)),
     lambda e, p: (_short(_PAT_NOR2.match(e).group(1)) + '_nor_'
                   + _short(_PAT_NOR2.match(e).group(2))),
     lambda e: f"AI: NOR({_PAT_NOR2.match(e).group(1)}, {_PAT_NOR2.match(e).group(2)})"),

    # NAND2
    (lambda e, p: bool(_PAT_NAND2.match(e)),
     lambda e, p: (_short(_PAT_NAND2.match(e).group(1)) + '_nand_'
                   + _short(_PAT_NAND2.match(e).group(2))),
     lambda e: f"AI: NAND({_PAT_NAND2.match(e).group(1)}, {_PAT_NAND2.match(e).group(2)})"),

    # MUX2: (sel & d1) | (!sel & d0)
    (_mux_check,
     lambda e, p: ('mux_' + _short(_PAT_MUX.match(e).group(2))
                   + '_' + _short(_PAT_MUX.match(e).group(4))),
     lambda e: (f"AI: MUX sel={_PAT_MUX.match(e).group(1)} "
                f"d1={_PAT_MUX.match(e).group(2)} d0={_PAT_MUX.match(e).group(4)}")),
]


# ---------------------------------------------------------------------------
# Per-pass naming functions
# ---------------------------------------------------------------------------

def apply_init_rules(lut_rows, existing_names, inserts):
    added = 0
    for cell, fn, init, pa, pb, pc, pd, z, expr in lut_rows:
        if not z or z in existing_names:
            continue
        rule = INIT_RULES.get(init)
        if not rule:
            continue
        name_fn, typ, conf, note_tmpl = rule
        m = _CELL.match(cell)
        if not m:
            continue
        row, col, sl, k = m.groups()
        name = _sanitise(name_fn(row, col, sl, k))
        ports = {
            ltr: (existing_names.get(net, net) if net else None)
            for ltr, net in zip("abcd", [pa, pb, pc, pd])
        }
        note = note_tmpl.replace("%PORTS%", _plist(ports) or "none")
        inserts.append((z, name, typ, conf, note))
        existing_names[z] = name
        added += 1
    return added


def apply_expr_rules(lut_rows, existing_names, inserts):
    added = 0
    for cell, fn, init, pa, pb, pc, pd, z, expr in lut_rows:
        if not z or z in existing_names or not expr:
            continue
        ports = {
            ltr: (existing_names.get(net) if net else None)
            for ltr, net in zip("abcd", [pa, pb, pc, pd])
        }
        if not _all_named(ports):
            continue
        # Substitute named ports into expression
        sub = expr
        for ltr, net in zip("abcd", [pa, pb, pc, pd]):
            if net and net in existing_names:
                sub = re.sub(rf'\b{re.escape(ltr)}\b', existing_names[net], sub)
        for match_fn, name_fn, note_fn in EXPR_RULES:
            try:
                if match_fn(sub, ports):
                    name = _sanitise(name_fn(sub, ports))
                    if name and name not in ('0', '1', 'unnamed'):
                        note = note_fn(sub)
                        inserts.append((z, name, "ctrl", "inferred", note))
                        existing_names[z] = name
                        added += 1
                        break
            except Exception:
                continue
    return added


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Auto-name nets from LUT init patterns and symbolic expressions"
    )
    ap.add_argument("--bitstream", default="V07")
    args = ap.parse_args()

    conn = connect()
    cur  = conn.cursor()

    cur.execute("SELECT id FROM bitstreams WHERE label=%s", (args.bitstream,))
    row = cur.fetchone()
    if not row:
        die(f"Bitstream {args.bitstream!r} not found")
    bs_id = row[0]

    cur.execute("""
        SELECT l.cell, l.fn, l.init, l.a, l.b, l.c, l.d, l.z, ls.expr
        FROM luts l
        JOIN lut_symbolic ls ON ls.bitstream=l.bitstream AND ls.lut_cell=l.cell
        WHERE l.bitstream=%s
    """, (bs_id,))
    lut_rows = cur.fetchall()

    cur.execute("SELECT net, name FROM net_names WHERE bitstream=%s", (bs_id,))
    existing_names = dict(cur.fetchall())
    cur.close()
    conn.close()

    all_inserts = []
    pass_num = 0
    total_added = 0

    while True:
        pass_num += 1
        inserts = []
        n1 = apply_init_rules(lut_rows, existing_names, inserts)
        n2 = apply_expr_rules(lut_rows, existing_names, inserts)
        n_pass = n1 + n2
        total_added += n_pass
        all_inserts.extend(inserts)
        print(f"  auto_name pass {pass_num}: +{n_pass} (init={n1} expr={n2})",
              flush=True)
        if n_pass == 0:
            break

    if not all_inserts:
        print("  auto_name: 0 new names (all already named)")
        return

    conn = connect()
    cur  = conn.cursor()
    cur.executemany("""
        INSERT INTO net_names (bitstream, net, name, description, confidence, source)
        VALUES (%s, %s, %s, %s, %s, 'auto')
        ON CONFLICT (bitstream, net) DO NOTHING
    """, [
        (bs_id, net, name, note, conf)
        for net, name, typ, conf, note in all_inserts
    ])
    conn.commit()
    inserted = cur.rowcount
    skipped  = total_added - inserted
    print(f"  auto_name: {inserted} new names inserted "
          f"({skipped} skipped — already named by TSV)")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
