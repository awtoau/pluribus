#!/usr/bin/env python3
"""Pluribus — structural Verilog emitter.

Reads the DB for a given bitstream and emits synthesisable structural Verilog
representing the recovered netlist.  Human names are used where known; raw
synthetic identifiers are used for everything else.

The output is intended for simulation and comprehension, not for FPGA
re-synthesis — hard-IP (EFB, clock spines) is not synthesisable in standard
Verilog and is emitted as comments only.

Usage
-----
  python3 fpga/pluribus/verilog.py [--bitstream V07] [--out out/V07.v] [--top aw2]
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import engine, die
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------

def _sanitise(raw: str) -> str:
    """Return a valid Verilog identifier from an arbitrary raw name.

    Replaces non-identifier characters with underscores.  Prepends 'n_' if
    the first character is a digit (Verilog identifiers must start with a
    letter or underscore).
    """
    # Replace any character not legal in a Verilog identifier with underscore.
    # Legal: [a-zA-Z0-9_$].  This covers brackets, whitespace, quotes, etc.
    ident = re.sub(r"[^a-zA-Z0-9_$]", "_", raw)
    # Strip trailing underscores introduced by e.g. "foo[0]" → "foo_0_"
    ident = ident.rstrip("_")
    if not ident:
        ident = "_"
    elif ident[0].isdigit():
        ident = "n_" + ident
    return ident


_VLOG_LITERAL_RE = re.compile(r"^\d+'b[01]+$")


def resolve_net(net: str | None, net_name_map: dict, const_net_map: dict) -> str:
    """Return the best Verilog expression for *net*.

    Priority:
      1. net is None                     → 'NC' (unconnected)
      2. net is already a Verilog literal (e.g. "1'b0") → pass through unchanged
      3. net is in const_net_map         → 1'b0 or 1'b1 literal
      4. net has a name in net_name_map  → sanitised human name
      5. fallback                        → sanitised raw net identifier

    The DB stores some columns (d, ce, clk, lsr) with Verilog literal strings
    like "1'b0" when the signal is tied to a constant; these must be passed
    through as-is rather than sanitised into invalid identifiers.
    """
    if net is None:
        return "NC"
    if _VLOG_LITERAL_RE.match(net):
        return net
    val = const_net_map.get(net)
    if val is not None:
        return f"1'b{val}"
    human = net_name_map.get(net)
    if human:
        return _sanitise(human)
    return _sanitise(net)


_SYNTHETIC_NAME_RE = re.compile(r"^reg_r\d+c\d+")


def resolve_cell(cell: str, cell_name_map: dict,
                 cell_clkname_map: dict | None = None) -> str:
    """Return a Verilog identifier for *cell*, preferring the human name.

    Fallback order:
    1. TSV human name that is NOT a synthetic grid-position name (reg_rNcN*)
    2. Clock-derived name: <short_clk>__<tile_slice>  (more informative than grid)
    3. Synthetic TSV name (reg_rNcN*) — last resort when no clock name is available
    4. Raw cell identifier
    """
    human = cell_name_map.get(cell)
    # Use human name only when it's not a synthetic reg_rNcN grid-position name
    if human and not _SYNTHETIC_NAME_RE.match(human):
        return _sanitise(human)
    if cell_clkname_map:
        clk = cell_clkname_map.get(cell)
        if clk:
            # Strip clk_hN_ prefix for brevity: clk_h2_spi_ser_a → spi_ser_a
            short = re.sub(r"^clk_h\d+_", "", clk)
            # cell is e.g. ff_r10c11_A0 → take the tile+slice suffix
            suffix = re.sub(r"^ff_", "", cell)   # r10c11_A0
            return _sanitise(f"{short}__{suffix}")
    # Fall back to synthetic name or raw cell id
    return _sanitise(human if human else cell)


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

def load_data(conn, bs_id: int) -> dict:
    """Fetch all tables needed for Verilog emission into a dict of lists/maps."""

    def q(sql):
        return conn.execute(text(sql), {"bs_id": bs_id}).fetchall()

    # FFs: (cell, clk, ce, d, q, lsr)
    ffs = q("SELECT cell, clk, ce, d, q, lsr FROM ffs WHERE bitstream=:bs_id ORDER BY cell")

    # LUTs: (cell, init, a, b, c, d, z, fn)
    luts = q("SELECT cell, init, a, b, c, d, z, fn FROM luts WHERE bitstream=:bs_id ORDER BY cell")

    # Pad map: (pin, label, direction, net_in, net_out)
    pads = q("SELECT pin, label, direction, net_in, net_out FROM pad_map WHERE bitstream=:bs_id ORDER BY pin")

    # EFB ports: (port_name, net)
    efb_ports = q("SELECT port_name, net FROM efb_ports WHERE bitstream=:bs_id ORDER BY port_name")

    # EBR buses: (block, bus_role, bit_index, port, net)
    ebr_buses = q("SELECT block, bus_role, bit_index, port, net FROM ebr_buses WHERE bitstream=:bs_id ORDER BY block, bus_role, bit_index")
    # EBR ports: (block, port, role, net)
    ebr_ctrl  = q("SELECT block, port, role, net FROM ebr_ports WHERE bitstream=:bs_id ORDER BY block, port")

    # Net names: net → (name, description)
    net_name_rows = q("SELECT net, name, description FROM net_names WHERE bitstream=:bs_id")
    net_name_map = {net: name for net, name, _desc in net_name_rows}
    net_desc_map = {net: desc for net, _name, desc in net_name_rows if desc}
    # Deduplicate: multiple nets can share a name (e.g. both K-slices of a 1-input LUT).
    # Append the net ID to disambiguate so wire declarations and references stay consistent.
    from collections import Counter as _NameCounter
    _name_counts = _NameCounter(net_name_map.values())
    _name_seen: dict[str, int] = {}
    for net in list(net_name_map):
        base = net_name_map[net]
        if _name_counts[base] > 1:
            idx = _name_seen.get(base, 0)
            _name_seen[base] = idx + 1
            net_name_map[net] = f"{base}_{net}"

    # Cell names: cell → (name, description)
    cell_name_rows = q("SELECT cell, name, description FROM cell_names WHERE bitstream=:bs_id")
    cell_name_map  = {cell: name for cell, name, _desc in cell_name_rows}
    # Deduplicate cell names the same way as net names
    _cell_name_counts = _NameCounter(cell_name_map.values())
    _cell_name_seen: dict[str, int] = {}
    for cell in list(cell_name_map):
        base = cell_name_map[cell]
        if _cell_name_counts[base] > 1:
            idx = _cell_name_seen.get(base, 0)
            _cell_name_seen[base] = idx + 1
            cell_name_map[cell] = f"{base}_{cell}"

    # Const nets: net → const_value ('0' or '1')
    const_net_rows = q("SELECT net, const_value FROM const_nets WHERE bitstream=:bs_id")
    const_net_map  = {net: val for net, val in const_net_rows}

    # Net stats: net → (fanout, fanin, is_clock, is_const, is_boundary)
    net_stat_rows = q("SELECT net, fanout, fanin, is_clock, is_const, is_boundary FROM net_stats WHERE bitstream=:bs_id")
    net_stats_map = {
        net: {"fanout": fanout, "fanin": fanin,
              "is_clock": is_clk, "is_const": is_const, "is_boundary": is_bnd}
        for net, fanout, fanin, is_clk, is_const, is_bnd in net_stat_rows
    }

    # Clock domains: clk_net → [ff_cell, ...]
    clk_domain_rows = q("SELECT clk_net, ff_cell FROM clock_domains WHERE bitstream=:bs_id")
    clock_domains: dict[str, list[str]] = {}
    for clk_net, ff_cell in clk_domain_rows:
        clock_domains.setdefault(clk_net, []).append(ff_cell)

    # All nets
    all_nets = [row[0] for row in q("SELECT name FROM nets WHERE bitstream=:bs_id ORDER BY name")]

    # Bitstream label / device / package
    meta = q("SELECT label, device, package FROM bitstreams WHERE id=:bs_id")[0]

    # Build clock-derived cell name map: cell → resolved clock name.
    # Populated for ALL FFs (not just unnamed) when the clock has a human name.
    # Used by resolve_cell to prefer clock-domain names over synthetic reg_rNcN names.
    cell_clkname_map: dict[str, str] = {}
    for cell, clk, _ce, _d, _q, _lsr in ffs:
        if clk:
            clk_human = net_name_map.get(clk)
            if clk_human:
                cell_clkname_map[cell] = clk_human

    # Build FF Q→cell map for wire naming: net → cell (so emit_wires can name Q wires)
    ff_q_cell_map: dict[str, str] = {q: cell for cell, _clk, _ce, _d, q, _lsr in ffs if q}

    # Build FF Q wire name map: cell → Verilog identifier that downstream logic uses to read
    # the FF's Q output.  This is the Q net's human name when available, otherwise derived
    # from the cell's human name + "_q".  emit_ffs uses this as the reg identifier so that
    # the reg name and the wire name (used by LUT input resolution) always match.
    ff_q_wire_map: dict[str, str] = {}
    for cell, _clk, _ce, _d, q, _lsr in ffs:
        if q is None:
            continue
        q_human = net_name_map.get(q)
        if q_human:
            ff_q_wire_map[cell] = _sanitise(q_human)
        elif cell in cell_name_map:
            ff_q_wire_map[cell] = _sanitise(f"{cell_name_map[cell]}_q")

    # Module port names (sanitised pad labels) — reg declarations must avoid these names
    # because ports are declared as wires in the module header.
    port_names: set[str] = {
        _sanitise(label)
        for _pin, label, direction, _ni, _no in pads
        if direction in ("in", "out", "bidir") and label
    }

    # Q wire names that are ALSO driven by a LUT continuous assign.
    # Adding `assign q_wire = reg;` for these would create a multi-driver conflict,
    # so emit_ffs must skip connect assigns for them.
    lut_z_nets: set[str] = {z for _cell, _init, _a, _b, _c, _d, z, _fn in luts if z}
    # Resolved LUT output identifiers: used by emit_ebr to avoid double-assigning
    # nets that already have a LUT driver (EBR dout bits routed through buffering LUTs).
    lut_driven_net_ids: set[str] = {resolve_net(z, net_name_map, const_net_map)
                                     for z in lut_z_nets
                                     if z is not None}
    # FF Q-wire identifiers that emit_ffs will assign: used by emit_ebr to skip
    # EBR dout assigns when the target net is already a FF Q output wire.
    ff_q_all_wire_ids: set[str] = set(ff_q_wire_map.values())
    dual_driven_q_wires: set[str] = {
        ff_q_wire_map[cell]
        for cell, _clk, _ce, _d, q, _lsr in ffs
        if q and q in lut_z_nets and cell in ff_q_wire_map
    }

    return {
        "ffs":              ffs,
        "luts":             luts,
        "pads":             pads,
        "efb_ports":        efb_ports,
        "ebr_buses":        ebr_buses,
        "ebr_ctrl":         ebr_ctrl,
        "net_name_map":     net_name_map,
        "net_desc_map":     net_desc_map,
        "cell_name_map":    cell_name_map,
        "cell_clkname_map": cell_clkname_map,
        "ff_q_cell_map":    ff_q_cell_map,
        "ff_q_wire_map":        ff_q_wire_map,
        "port_names":           port_names,
        "dual_driven_q_wires":  dual_driven_q_wires,
        "lut_driven_net_ids":   lut_driven_net_ids,
        "ff_q_all_wire_ids":    ff_q_all_wire_ids,
        "const_net_map":    const_net_map,
        "net_stats_map":    net_stats_map,
        "clock_domains":    clock_domains,
        "all_nets":         all_nets,
        "bs_label":         meta[0],
        "device":           meta[1],
        "package":          meta[2],
    }


# ---------------------------------------------------------------------------
# Section emitters — each returns a list of strings (lines)
# ---------------------------------------------------------------------------

def emit_header(data: dict, top_name: str) -> list[str]:
    """File header comment block and `timescale directive."""
    n_named_nets  = len(data["net_name_map"])
    n_named_cells = len(data["cell_name_map"])
    n_total_nets  = len(data["all_nets"])
    n_total_cells = len(data["ffs"]) + len(data["luts"])
    label   = data["bs_label"]
    device  = data["device"]
    package = data["package"]

    return [
        f"// Pluribus structural Verilog — {label} ({device} {package})",
        "// Generated by verilog.py — DO NOT EDIT (regenerated on every build)",
        f"// Named nets: {n_named_nets}/{n_total_nets}  "
        f"Named cells: {n_named_cells}/{n_total_cells}",
        "// Cold run: all unnamed objects use synthetic identifiers",
        "//",
        "// !! CONFIG FLASH DATA WARNING !!",
        "// This Verilog describes the LOGIC portion of the bitstream (V07.bin).",
        "// V07.bin is a factory-clean bitstream with NO calibration data.",
        "// On a LIVE device the first 784 bytes of the FPGA config flash",
        "// (pages 0-48, 49 × 16 B) contain the calibration block — NOT logic.",
        "// If you dump a live device's config flash, bytes 0x000-0x30F are DATA",
        "// (scope/DAC cal coefficients) and must NOT be disassembled as bitstream.",
        "// The bitstream itself begins after the calibration block.",
        "// See docs/hardware/fpga.md — 'Calibration data in config flash'.",
        "",
        "`timescale 1ns/1ps",
        "",
    ]


def emit_ports(data: dict, top_name: str) -> list[str]:
    """Module declaration with port list.

    Resolved pads become actual ports (input/output/inout).
    Unresolved pads are listed as comments at the end of the port list.
    """
    net_name_map = data["net_name_map"]
    const_net_map = data["const_net_map"]
    pads = data["pads"]

    # Separate resolved pads (have at least one fabric net) from unresolved
    resolved   = []
    unresolved = []
    for pin, label, direction, net_in, net_out in pads:
        if direction not in ("in", "out", "bidir"):
            unresolved.append((pin, label, direction, net_in, net_out))
            continue
        if net_in is None and net_out is None:
            unresolved.append((pin, label, direction, net_in, net_out))
            continue
        resolved.append((pin, label, direction, net_in, net_out))

    lines = [f"module {top_name} ("]

    # Resolved ports — track seen names to de-dup blank labels (e.g. multiple pins named "_")
    if resolved:
        lines.append(f"    // Physical pads — resolved ({len(resolved)})")
    seen_port_names: set[str] = set()
    for i, (pin, label, direction, net_in, net_out) in enumerate(resolved):
        fabric_net = net_in if direction == "in" else net_out
        if direction == "bidir":
            # For bidir we show both; pick net_in if available, else net_out
            fabric_net = net_in or net_out
        direction_kw = {"in": "input  wire", "out": "output wire", "bidir": "inout  wire"}[direction]
        base_name = _sanitise(label)
        # Unknown-label pins sanitise to bare "_" — always use pin<N> so they're unique
        # and don't shadow internal wires.  Also handle any accidental name collision.
        if base_name == "_" or base_name in seen_port_names:
            port_name = f"pin{pin}"
        else:
            port_name = base_name
        seen_port_names.add(port_name)
        is_last = (i == len(resolved) - 1) and not unresolved
        comma = "" if is_last else ","
        lines.append(f"    {direction_kw} {port_name}{comma}   // pin {pin}  net {fabric_net}")

    # Unresolved pads — comment block
    if unresolved:
        lines.append(f"    // Physical pads — unresolved ({len(unresolved)}, CIB bug #57)")
        for pin, label, direction, net_in, net_out in unresolved:
            lines.append(f"    // pin {pin} {label} direction={direction} — net unknown")

    lines.append(");")
    lines.append("")
    return lines


def emit_wires(data: dict) -> list[str]:
    """Wire declarations for all internal nets (not module ports)."""
    net_name_map      = data["net_name_map"]
    net_desc_map      = data["net_desc_map"]
    const_net_map     = data["const_net_map"]
    net_stats_map     = data["net_stats_map"]
    cell_clkname_map  = data["cell_clkname_map"]
    ff_q_cell_map     = data["ff_q_cell_map"]
    cell_name_map     = data["cell_name_map"]
    pads              = data["pads"]
    all_nets          = data["all_nets"]

    # Build set of port nets AND port name strings.
    # Both must be excluded from wire declarations:
    # - port_nets: catches pad boundary nets (pad_XX) and fabric nets recorded in pad_map
    # - port_names: catches internal nets whose TSV name collides with a port identifier
    #   (e.g. n2508 named "ADC_ENCA" where pad_map has net_in=None so n2508 escapes port_nets)
    port_nets: set[str] = set()
    port_names: set[str] = set()
    for _pin, _label, direction, net_in, net_out in pads:
        if direction not in ("in", "out", "bidir"):
            continue
        if net_in is None and net_out is None:
            continue
        if net_in:
            port_nets.add(net_in)
        if net_out:
            port_nets.add(net_out)
        port_names.add(_sanitise(_label))

    def _wire_name(net: str) -> str:
        """Resolve net to a Verilog wire identifier, with clock-derived fallback."""
        if net in net_name_map:
            return _sanitise(net_name_map[net])
        if net in const_net_map:
            return _sanitise(net)
        src_cell = ff_q_cell_map.get(net)
        if src_cell:
            cell_human = cell_name_map.get(src_cell)
            if cell_human:
                return _sanitise(f"{cell_human}_q")
            clk_name = cell_clkname_map.get(src_cell)
            if clk_name:
                short = re.sub(r"^clk_h\d+_", "", clk_name)
                suffix = re.sub(r"^ff_", "", src_cell)
                return _sanitise(f"{short}__{suffix}_q")
        return resolve_net(net, net_name_map, const_net_map)

    # Split into groups
    named_nets   = []
    clkderiv_nets = []
    unnamed_nets = []
    const_nets   = []
    for net in all_nets:
        if net in port_nets:
            continue
        if _wire_name(net) in port_names:
            continue
        if net in const_net_map:
            const_nets.append(net)
        elif net in net_name_map:
            named_nets.append(net)
        elif net in ff_q_cell_map and (
                cell_name_map.get(ff_q_cell_map[net]) or
                cell_clkname_map.get(ff_q_cell_map[net])):
            clkderiv_nets.append(net)
        else:
            unnamed_nets.append(net)

    def _wire_line(net: str) -> str:
        wire_name = _wire_name(net)
        if net in const_net_map:
            return f"    wire {wire_name} = 1'b{const_net_map[net]};"
        stats = net_stats_map.get(net, {})
        comment_parts = []
        if net in net_name_map:
            desc = net_desc_map.get(net)
            comment_parts.append(desc if desc else net_name_map[net])
        elif net in ff_q_cell_map:
            src = ff_q_cell_map[net]
            clk = cell_clkname_map.get(src, "?")
            comment_parts.append(f"Q output of {src}  clk={clk}")
        else:
            comment_parts.append("(unnamed)")
        if stats.get("is_clock"):
            comment_parts.append("clock spine (hard IP source)")
        elif stats.get("fanin", 1) == 0:
            comment_parts.append("no driver — floating?")
        comment = "  // " + " — ".join(comment_parts) if comment_parts else ""
        return f"    wire {wire_name};{comment}"

    # Sort named by human name; clock-derived by derived name; unnamed numerically
    named_nets.sort(key=lambda n: net_name_map[n])
    clkderiv_nets.sort(key=lambda n: _wire_name(n))
    def _net_sort_key(n):
        if n.startswith("n") and n[1:].isdigit():
            return (0, int(n[1:]))
        return (1, n)
    unnamed_nets.sort(key=_net_sort_key)

    lines = [
        "    // ── Wire declarations ─────────────────────────────────────────────────",
        f"    // {len(named_nets)} named  {len(clkderiv_nets)} clock-derived"
        f"  {len(unnamed_nets)} unnamed  {len(const_nets)} const",
    ]

    # NC (not-connected) sentinel — LUT inputs left unconnected are tied to GND.
    lines.append("    wire NC = 1'b0;  // unconnected LUT inputs — tied to GND in MachXO2")

    if const_nets:
        lines.append("    // Constants")
        for net in const_nets:
            lines.append(_wire_line(net))
        lines.append("")

    if named_nets:
        lines.append("    // Named nets (TSV-assigned names, alphabetical)")
        for net in named_nets:
            lines.append(_wire_line(net))
        lines.append("")

    if clkderiv_nets:
        lines.append("    // Clock-derived names (unnamed FF Q outputs, named by clock domain)")
        for net in clkderiv_nets:
            lines.append(_wire_line(net))
        lines.append("")

    if unnamed_nets:
        lines.append("    // Unnamed nets (no TSV entry, no clock derivation)")
        for net in unnamed_nets:
            lines.append(_wire_line(net))

    lines.append("")
    return lines


def emit_efb_comment(data: dict) -> list[str]:
    """Comment block describing EFB port connections.

    The EFB is hard IP and cannot be instantiated in plain structural Verilog.
    We document the port→net mapping as comments so a reader can trace signals.
    """
    efb_ports    = data["efb_ports"]
    net_name_map = data["net_name_map"]
    const_net_map = data["const_net_map"]

    if not efb_ports:
        return []

    lines = [
        "    // ── EFB port connections ──────────────────────────────────────────────",
        "    // EFB is hard IP — not instantiable in standard Verilog.",
        "    // Port→net mapping is shown as comments; nets are declared as wires above.",
    ]
    for port_name, net in efb_ports:
        wire_name = resolve_net(net, net_name_map, const_net_map)
        lines.append(f"    // EFB.{port_name} → {wire_name}  (raw net: {net})")
    lines.append("")
    return lines


def _simplify_lut(init: str, a: str, b: str, c: str, d: str) -> str | None:
    """Reduce a 4-input LUT to a direct Verilog operator expression where possible.

    NC and 1'b0 inputs are treated as constant 0; 1'b1 inputs as constant 1.
    Returns a Verilog expression string for the output, or None when the
    function needs 3+ live inputs (too complex to name in a single expression).

    init: 16-char LSB-first truth table (index i = a + 2b + 4c + 8d).
    """
    ZERO = {"NC", "1'b0"}
    ONE  = {"1'b1"}

    ports  = [(0, a), (1, b), (2, c), (3, d)]
    live   = [(pos, sig) for pos, sig in ports if sig not in ZERO and sig not in ONE]
    fixed1 = [pos for pos, sig in ports if sig in ONE]

    if len(live) > 2:
        return None

    # Effective truth table for the live inputs only (indexed by bit position
    # within live[], bit 0 = live[0]).  Fixed inputs contribute a constant
    # offset into the full 16-entry init string.
    const_idx = sum(1 << pos for pos in fixed1)
    eff = []
    for i in range(1 << len(live)):
        idx = const_idx
        for bit, (pos, _) in enumerate(live):
            if (i >> bit) & 1:
                idx |= (1 << pos)
        eff.append(init[idx])
    tt = ''.join(eff)

    def p(s: str) -> str:
        return f'({s})' if ' ' in s else s

    if len(live) == 0:
        return f"1'b{tt[0]}"

    if len(live) == 1:
        x = live[0][1]
        return {'01': x, '10': f'~{x}'}.get(tt)

    x, y = live[0][1], live[1][1]
    px, py = p(x), p(y)
    TABLE = {
        '0000': "1'b0",   '1111': "1'b1",
        '0101': x,         '1010': f'~{x}',
        '0011': y,         '1100': f'~{y}',
        '0001': f'{px} & {py}',     '1110': f'~({px} & {py})',
        '0111': f'{px} | {py}',     '1000': f'~({px} | {py})',
        '0110': f'{px} ^ {py}',     '1001': f'~({px} ^ {py})',
        '0010': f'~{px} & {py}',    '1011': f'~{px} | {py}',
        '0100': f'{px} & ~{py}',    '1101': f'{px} | ~{py}',
    }
    return TABLE.get(tt)


def _lut_init_to_case(init: str, z_name: str, a: str, b: str, c: str, d: str, cell_name: str = "") -> list[str]:
    """Emit an assign for a LUT with no structured fn tag.

    First tries _simplify_lut() — for LUTs with ≤2 live inputs this emits a
    direct operator expression (x ^ y, x & y, etc.) instead of a localparam.
    Falls back to a localparam bit-select for more complex truth tables.

    init: 16-char LSB-first truth table (index 0 = a=0,b=0,c=0,d=0).
    cell_name: human cell name to use for the localparam identifier; empty
               string tells us to use z_name instead (avoids _lut_lut_lut_…).
    """
    expr = _simplify_lut(init, a, b, c, d)
    if expr is not None:
        return [f"    assign {z_name} = {expr};"]

    # Localparam bit-select fallback
    init_msb_first = init[::-1]
    lp_base = cell_name if cell_name else z_name
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', lp_base)
    # Strip any leading lut_ repetitions to prevent _lut_lut_lut_… prefixes
    sanitized = re.sub(r'^(lut_)+', '', sanitized) or sanitized
    lp_name = f"_lut_{sanitized}"
    sel_expr = "{" + ", ".join([d, c, b, a]) + "}"

    return [
        f"    localparam [15:0] {lp_name} = 16'b{init_msb_first};",
        f"    assign {z_name} = {lp_name}[{sel_expr}];",
    ]


def emit_luts(data: dict) -> list[str]:
    """Emit LUTs as assign statements.

    Structured fn tags (AND, OR, XOR, etc.) become direct boolean expressions.
    COMBO / None → bit-select of the 16-bit init table.
    """
    luts         = data["luts"]
    net_name_map = data["net_name_map"]
    const_net_map = data["const_net_map"]
    cell_name_map = data["cell_name_map"]

    # Input pads are declared as `input wire PORT_NAME` in the module header.
    # Pad loopback arcs can make a LUT output net share the same DSU root as an
    # input pad net, causing z_name to resolve to PORT_NAME.  Emitting
    # `assign PORT_NAME = ...` for those creates a conflicting driver.
    input_port_names: set[str] = {
        _sanitise(label)
        for _pin, label, direction, _ni, _no in data["pads"]
        if direction == "in" and label
    }

    def rn(net):
        return resolve_net(net, net_name_map, const_net_map)

    # Convert symbolic function-call fn tags to Verilog operator templates.
    # Applied BEFORE port-letter substitution so arguments are still single chars.
    _FN_RULES = [
        (re.compile(r"^(INV|NOT)\(([abcd])\)$"),     lambda m: f"~{m.group(2)}"),
        (re.compile(r"^BUF\(([abcd])\)$"),            lambda m: m.group(1)),
        (re.compile(r"^AND\(([abcd]),([abcd])\)$"),   lambda m: f"{m.group(1)} & {m.group(2)}"),
        (re.compile(r"^OR\(([abcd]),([abcd])\)$"),    lambda m: f"{m.group(1)} | {m.group(2)}"),
        (re.compile(r"^XOR\(([abcd]),([abcd])\)$"),   lambda m: f"{m.group(1)} ^ {m.group(2)}"),
        (re.compile(r"^NAND\(([abcd]),([abcd])\)$"),  lambda m: f"~({m.group(1)} & {m.group(2)})"),
        (re.compile(r"^NOR\(([abcd]),([abcd])\)$"),   lambda m: f"~({m.group(1)} | {m.group(2)})"),
        (re.compile(r"^XNOR\(([abcd]),([abcd])\)$"),  lambda m: f"~({m.group(1)} ^ {m.group(2)})"),
    ]
    def _fn_to_vlog(fn: str) -> str:
        for pat, xform in _FN_RULES:
            m = pat.match(fn)
            if m:
                return xform(m)
        return fn

    lines = [
        "    // ── LUTs ──────────────────────────────────────────────────────────────",
        f"    // {len(luts)} LUTs — structured fn → assign expression; COMBO → case bit-select",
    ]

    # Track which output net identifiers have already been assigned.
    # The lifter can extract DPRAM tiles as both a dpram_* cell AND a lut_* cell,
    # both mapped to the same output net.  Emitting both creates conflicting
    # continuous assigns; keep only the first (dpram_* sorts before lut_* in the
    # DB ORDER BY cell, so the DPRAM interpretation wins — it has the correct
    # address/data wiring while the lut_* entry reflects the raw init table).
    _assigned_lut_outputs: set[str] = set()

    for cell, init, pa, pb, pc, pd, out_z, fn in luts:
        if out_z is None:
            # Output is not connected to any fabric net — skip
            continue

        z_name    = rn(out_z)
        # Skip LUTs whose output is a power/ground net — can't assign to a constant
        if z_name in ("1'b0", "1'b1"):
            continue

        # Skip LUTs whose output net resolves to an input port name.
        if z_name in input_port_names:
            continue

        # Skip duplicate drivers: a previous LUT already drives this net.
        if z_name in _assigned_lut_outputs:
            continue
        cell_human = cell_name_map.get(cell)          # None if no human annotation
        cell_name  = resolve_cell(cell, cell_name_map)  # for display/comments
        a_expr = rn(pa)
        b_expr = rn(pb)
        c_expr = rn(pc)
        d_expr = rn(pd)

        if fn is None or fn.startswith("COMBO"):
            # Pass human name for localparam naming; empty → use z_name (avoids lut_lut_lut…)
            lp_key = _sanitise(cell_human) if cell_human else ""
            lut_lines = _lut_init_to_case(init, z_name, a_expr, b_expr, c_expr, d_expr, lp_key)
            lut_lines[-1] += f"  // {cell_name}  init={init}"
            lines.extend(lut_lines)

        elif fn == "CONST0":
            lines.append(f"    assign {z_name} = 1'b0;  // {cell_name} CONST0")

        elif fn == "CONST1":
            lines.append(f"    assign {z_name} = 1'b1;  // {cell_name} CONST1")

        else:
            # Structured fn: convert function-call syntax to operators first,
            # then substitute port letters with resolved net names.
            fn_op = _fn_to_vlog(fn)
            port_map = {"a": a_expr, "b": b_expr, "c": c_expr, "d": d_expr}

            def replace_port(m):
                letter = m.group(0)
                expr = port_map.get(letter, letter)
                # Wrap complex expressions in parentheses for safety
                if " " in expr or "," in expr:
                    return f"({expr})"
                return expr

            vlog_expr = re.sub(r"\b([abcd])\b", replace_port, fn_op)
            lines.append(f"    assign {z_name} = {vlog_expr};  // {cell_name}")

        _assigned_lut_outputs.add(z_name)

    lines.append("")
    return lines


def emit_ffs(data: dict) -> list[str]:
    """Emit flip-flops as reg declarations and always blocks.

    Grouping strategy:
    - FFs with d='1'b0' and ce='1'b1' and matching (clk, lsr) are "stuck-at-reset".
      These are collapsed into a single always block per (clk, lsr) pair with a
      comment showing the count.  They never change state.
    - All other FFs are emitted individually.
    """
    ffs              = data["ffs"]
    net_name_map     = data["net_name_map"]
    const_net_map    = data["const_net_map"]
    cell_name_map    = data["cell_name_map"]
    cell_clkname_map = data["cell_clkname_map"]
    ff_q_wire_map    = data["ff_q_wire_map"]
    port_names       = data["port_names"]

    def rn(net):
        return resolve_net(net, net_name_map, const_net_map)

    def rc(cell):
        return resolve_cell(cell, cell_name_map, cell_clkname_map)

    def reg_id(cell: str) -> str:
        """Verilog reg identifier for the reg declaration and always-block writes.

        Uses rc() (cell-derived name) so the identifier never conflicts with Q wire
        names, port declarations, or LUT continuous assigns.  A separate connect
        assign `assign q_wire = reg_id;` is emitted after all always blocks for
        Q nets that are not also LUT-driven.
        """
        return rc(cell)

    # ── Classify each FF ────────────────────────────────────────────────────
    # "stuck"   : d=1'b0, ce=VCC — permanently zero, collapsed into groups
    # "ce_clear": d=1'b0, ce=fabric net — clears to 0 when CE fires, grouped
    # "active"  : d is a real fabric net — emitted individually
    stuck_ffs:    list[tuple] = []   # (cell, clk, ce, d, q, lsr)
    ce_clear_ffs: list[tuple] = []
    active_ffs:   list[tuple] = []

    for row in ffs:
        cell, clk, ce, d, q, lsr = row
        ce_resolved = rn(ce) if ce is not None else "1'b1"
        d_resolved  = rn(d)  if d  is not None else "NC"
        if d_resolved == "1'b0" and ce_resolved == "1'b1":
            stuck_ffs.append(row)
        elif d_resolved == "1'b0":
            ce_clear_ffs.append(row)
        else:
            active_ffs.append(row)

    lines = [
        "    // ── Flip-flops ─────────────────────────────────────────────────────────",
        f"    // {len(ffs)} total FFs: {len(stuck_ffs)} stuck-at-VCC, "
        f"{len(ce_clear_ffs)} CE-gated-clear, {len(active_ffs)} real-D",
    ]

    # ── Reg declarations ────────────────────────────────────────────────────
    # Multiple FFs can share the same Q net (bus structure); declare each reg
    # only once.  All associated always blocks still write to the shared reg.
    _declared_regs: set[str] = set()
    for cell, clk, ce, d, q, lsr in ffs:
        cell_ident  = reg_id(cell)
        if cell_ident in _declared_regs:
            continue
        _declared_regs.add(cell_ident)
        human_label = cell_name_map.get(cell, "")
        clk_name    = rn(clk) if clk else "?"
        ce_name     = rn(ce)  if ce  else "1'b1"
        # Comment: human name if available, otherwise clock+CE for context
        if human_label:
            comment = f"  // {human_label}  clk={clk_name}"
        else:
            ce_part = f"  CE={ce_name}" if ce_name != "1'b1" else ""
            comment = f"  // clk={clk_name}{ce_part}"
        lines.append(f"    reg {cell_ident};{comment}")
    lines.append("")

    # ── Stuck-at-reset FFs — collapsed by (clk, lsr) group ─────────────────
    if stuck_ffs:
        lines.append(
            f"    // ── Stuck-at-reset FFs ({len(stuck_ffs)}) — collapsed by (clk, lsr) ─"
        )
        lines.append(
            "    // These FFs have d=1'b0 and CE=1'b1: they hold 0 permanently unless"
        )
        lines.append("    // LSR toggles, which it never does in normal operation.")
        lines.append("")

        # Group by clock only — d=0 in all cases so LSR is irrelevant
        from collections import defaultdict
        stuck_groups: dict[str, list] = defaultdict(list)
        for row in stuck_ffs:
            cell, clk, ce, d, q, lsr = row
            clk_expr = rn(clk) if clk else "/* no_clk */"
            stuck_groups[clk_expr].append(cell)

        for clk_expr, cells in sorted(stuck_groups.items()):
            lines.append(f"    // {len(cells)} FFs stuck at 0 on posedge {clk_expr}")
            lines.append(f"    always @(posedge {clk_expr}) begin")
            for cell in cells:
                lines.append(f"        {reg_id(cell)} <= 1'b0;")
            lines.append("    end")
            lines.append("")

    # ── CE-gated clear FFs — collapsed by (clk, combined-condition) ─────────
    if ce_clear_ffs:
        from collections import defaultdict as _dd
        lines.append(
            f"    // ── CE-gated clear FFs ({len(ce_clear_ffs)}) — d=0, clear when CE asserted ─"
        )
        lines.append(
            "    // D=0 with a real CE: the register clears to 0 whenever CE fires."
        )
        lines.append(
            "    // Where LSR is also present both paths → 0, so condition is (LSR | CE)."
        )
        lines.append("")

        ce_groups: dict[tuple, list] = _dd(list)
        for row in ce_clear_ffs:
            cell, clk, ce, d, q, lsr = row
            clk_expr = rn(clk) if clk else "/* no_clk */"
            ce_expr  = rn(ce)  if ce  else "1'b1"
            lsr_expr = rn(lsr) if lsr else None
            # Merge lsr + ce into one condition when both lead to 0
            if lsr_expr and lsr_expr not in ("1'b0", "NC"):
                cond = f"{lsr_expr} | {ce_expr}"
            else:
                cond = ce_expr
            ce_groups[(clk_expr, cond)].append(cell)

        for (clk_expr, cond), cells in sorted(ce_groups.items()):
            lines.append(f"    // {len(cells)} FFs clear on ({cond}) @ posedge {clk_expr}")
            lines.append(f"    always @(posedge {clk_expr}) begin")
            lines.append(f"        if ({cond}) begin")
            for cell in cells:
                lines.append(f"            {reg_id(cell)} <= 1'b0;")
            lines.append("        end")
            lines.append("    end")
            lines.append("")

    # ── Active (real-D) FFs ──────────────────────────────────────────────────
    if active_ffs:
        lines.append(f"    // ── Real-D FFs ({len(active_ffs)}) — D inputs from fabric ────────────────────")

        for cell, clk, ce, d, q, lsr in active_ffs:
            cell_ident = reg_id(cell)
            clk_expr   = rn(clk)  if clk  else "/* no_clk */"
            ce_expr    = rn(ce)   if ce   else "1'b1"
            d_expr     = rn(d)    if d    else "NC"
            lsr_expr   = rn(lsr)  if lsr  else None
            human      = cell_name_map.get(cell, "")
            comment    = f"  // {human}" if human else ""

            lines.append(f"    always @(posedge {clk_expr}) begin{comment}")
            if lsr_expr and lsr_expr not in ("1'b0", "NC"):
                lines.append(f"        if ({lsr_expr})")
                lines.append(f"            {cell_ident} <= 1'b0;")
                if ce_expr != "1'b1":
                    lines.append(f"        else if ({ce_expr})")
                    lines.append(f"            {cell_ident} <= {d_expr};")
                else:
                    lines.append(f"        else")
                    lines.append(f"            {cell_ident} <= {d_expr};")
            elif ce_expr != "1'b1":
                lines.append(f"        if ({ce_expr})")
                lines.append(f"            {cell_ident} <= {d_expr};")
            else:
                lines.append(f"        {cell_ident} <= {d_expr};")
            lines.append("    end")

    # ── Q-output connect assigns ──────────────────────────────────────────────
    # reg_id() = cell-derived name; Q wire = what downstream LUTs reference.
    # They differ for every FF, so we emit `assign q_wire = reg;` to connect them.
    #
    # Skip cases where the assign would conflict:
    #   - Q net is also a LUT z-output (continuous assign already drives it →
    #     adding a second assign would create an ambiguous multi-driver).
    #   - Q net is a module port (port wire is declared in emit_ports; assign is
    #     fine, but we rely on emit_ports to wire it up instead).
    #   - Q net has no wire mapping (no-op).
    lut_driven_nets: set[str] = {
        fw for fw, _map in [(ff_q_wire_map.get(c), c) for c, *_ in ffs]
        if fw is not None
    }
    # Build set of Q net wire names that are also driven by a LUT assign in emit_luts.
    # We can detect this by checking if the Q net itself is a LUT z-output: the
    # lut output name (rn(lut.z)) would equal the Q wire name for that net.
    # Simpler: build from ff_q_wire_map vs luts data we don't have here —
    # instead pre-compute in load_data and pass as data["dual_driven_q_wires"].
    dual_driven = data.get("dual_driven_q_wires", set())

    seen_q_assigns: set[str] = set()
    for cell, _clk, _ce, _d, q, _lsr in ffs:
        if q is None:
            continue
        q_wire = ff_q_wire_map.get(cell)
        if q_wire is None:
            continue
        if q_wire in seen_q_assigns:
            continue
        if q_wire in port_names:
            continue  # port: pad logic handles the connection
        if q_wire in dual_driven:
            continue  # LUT already drives this wire; second assign would conflict
        r = reg_id(cell)
        seen_q_assigns.add(q_wire)
        lines.append(f"    assign {q_wire} = {r};  // Q output")
    if seen_q_assigns:
        lines.append("")

    lines.append("")
    return lines


def emit_trigger_comment(data: dict) -> list[str]:
    """Comment block explaining the trigger / capture-arm architecture.

    The trigger comparator and EBR write-counter live inside EFB hard IP and
    are invisible to the fabric netlist.  This block documents the inferred
    architecture so the ghost nets in the Verilog are interpretable.
    """
    return [
        "    // ── Trigger & capture-arm architecture ──────────────────────────────",
        "    //",
        "    // The trigger comparator is inside EFB hard IP — NOT in synthesisable",
        "    // fabric.  This is why Yosys post-opt reduces the design to 4 cells.",
        "    //",
        "    // Sequence (from fpga-spi.md §8 + netlist inference):",
        "    //",
        "    //   1. MCU writes CTRL 0xc8/0x00/0x07 (ARM_TRIGGER|RUN|ENABLE_ACQ)",
        "    //      → EFB sets ebr_arm = 1 via ghost path (not visible in fabric)",
        "    //      → EBR JLSR deasserted → ADC ring-buffer write counters running",
        "    //",
        "    //   2. ADC samples flow continuously: ADC_D[7:0]A/B → EBR write ports",
        "    //      via ghost FFs (ghost_d_* in this Verilog).  The write address",
        "    //      is a free-running counter in the EFB (ebr_waddr_* shared bus).",
        "    //",
        "    //   3. EFB compares each sample against trigger level (REG 0x06/0x08)",
        "    //      and hysteresis band (REG 0x03).  When edge condition is met",
        "    //      (polarity = REG 0x17 bit 0) the comparator asserts three ghost",
        "    //      outputs: n613, n614, n615.",
        "    //",
        "    //   4. ebr_waddr_ce = COMBO3(n613, n614, n615)  [fabric LUT, visible]",
        "    //      On the next ADC clock edge, the arm FF captures D=1'b0:",
        "    //        always @(posedge clk_h2_adc_a_pipe)",
        "    //            if (ebr_arm_ce) ebr_arm <= 1'b0;",
        "    //      ebr_arm → 0 deasserts EBR JLSR → write counters stop.",
        "    //",
        "    //   5. MCU polls STATUS (0xa0/0x00) bit 1 = BUSY until 0.",
        "    //      Then reads ring-buffer end address (0xa0/0x03) and bursts",
        "    //      6144 bytes via 0xa4 cmd (fw_fpga_read_samples).",
        "    //",
        "    // Ghost nets in trigger path (EFB outputs, fanin=0 in fabric):",
        "    //   n613, n614, n615 — trigger comparator outputs → ebr_waddr_ce LUT",
        "    //   ebr_arm_ce (n1881) — ARM strobe from EFB → arm FF clock-enable",
        "    //",
        "    // Surviving fabric cells after Yosys opt (the rest is constant-0):",
        "    //   U1_DS  = NOR(n1267, reg_r7c11_q[4])  — CH1 AFE serial data bit",
        "    //   U1_SHCP = LUT({reg_r9c6_q[7],0,n1525}) — CH1 shift clock mux",
        "    //   U7_SHCP = LUT({n1526,0,n1525})         — CH2 shift clock mux",
        "    //   ADC_D5B pass-through (n1713)            — ghost EBR write feed",
        "    // ─────────────────────────────────────────────────────────────────────",
        "",
    ]


def emit_clock_comment(data: dict) -> list[str]:
    """Comment block summarising the clock spine (hard IP driven, fanin=0)."""
    clock_domains = data["clock_domains"]
    net_name_map  = data["net_name_map"]
    const_net_map = data["const_net_map"]

    if not clock_domains:
        return []

    lines = [
        "    // ── Clock spine ──────────────────────────────────────────────────────",
        "    // Clock nets are ghost nets — driven by hard IP (PLL / clock spine),",
        "    // fanin=0 in the fabric.  They are declared as wires above.",
    ]
    for clk_net in sorted(clock_domains):
        ff_count = len(clock_domains[clk_net])
        wire_name = resolve_net(clk_net, net_name_map, const_net_map)
        lines.append(f"    // {wire_name}  ({ff_count} FFs)")
    lines.append("")
    return lines


def emit_unresolved_pads_comment(data: dict) -> list[str]:
    """Comment block for pads where net_in/net_out is unknown (CIB bug #57)."""
    pads = data["pads"]

    unresolved = [
        (pin, label, direction)
        for pin, label, direction, net_in, net_out in pads
        if net_in is None and net_out is None
        and direction in ("in", "out", "bidir")
    ]

    if not unresolved:
        return []

    lines = [
        "    // ── Unresolved pads ──────────────────────────────────────────────────",
        f"    // {len(unresolved)} pads where the fabric net could not be recovered (CIB bug #57)",
    ]
    for pin, label, direction in unresolved:
        lines.append(f"    // pin {pin} {label} direction={direction} — fabric net unknown")
    lines.append("")
    return lines


def emit_ebr(data: dict) -> list[str]:
    """Emit behavioral models for EBR blocks.

    Block classification is derived entirely from net names in the DB —
    no tile positions are hardcoded so layout changes in awto-2000 or the
    Pluribus DB are automatically reflected here.

    Classification rules (applied to all nets connected to each block):
      awg_*  nets present → AWG waveform table  (INITVAL: 0xDEAD, no ramp)
      ebr_waddr_* / ebr_raddr_* present → ADC ring buffer (INITVAL: ramp)
      neither → unknown / generic (INITVAL: 0)
    """
    rn = lambda net: resolve_net(net, data["net_name_map"], data["const_net_map"])
    nm = data["net_name_map"]

    from collections import defaultdict

    # Gather per-block connectivity
    buses: dict[str, dict] = defaultdict(lambda: {"write_data": {}, "read_data": {},
                                                    "write_addr": {}, "read_addr": {}})
    for row in data["ebr_buses"]:
        buses[row.block][row.bus_role][row.bit_index] = row.net

    ctrl: dict[str, dict] = defaultdict(dict)
    for row in data["ebr_ctrl"]:
        ctrl[row.block][row.port] = row.net

    # Classify blocks from net names — no hardcoded tile positions
    def _block_kind(block):
        all_nets = (
            list(buses[block].get("write_data", {}).values()) +
            list(buses[block].get("read_data",  {}).values()) +
            list(buses[block].get("write_addr", {}).values()) +
            list(buses[block].get("read_addr",  {}).values()) +
            list(ctrl[block].values())
        )
        names = {nm.get(n, "") for n in all_nets if n}
        if any(name.startswith("awg_") for name in names):
            return "awg"
        if any(name.startswith(("ebr_waddr_", "ebr_raddr_")) for name in names):
            return "adc"
        return "unknown"

    all_blocks = sorted(set(r.block for r in data["ebr_buses"]) |
                        set(r.block for r in data["ebr_ctrl"]))

    adc_blocks = [b for b in all_blocks if _block_kind(b) == "adc"]
    awg_blocks = [b for b in all_blocks if _block_kind(b) == "awg"]
    unk_blocks = [b for b in all_blocks if _block_kind(b) == "unknown"]

    adc_label = "/".join(adc_blocks) if adc_blocks else "none"
    awg_label = "/".join(awg_blocks) if awg_blocks else "none"

    lines: list[str] = [
        "",
        "    // =========================================================",
        "    // EBR (Embedded Block RAM) — behavioral models",
        "    // =========================================================",
        "    // WARNING: EBR is hard IP. These behavioral models represent",
        "    // structural connections recovered from the bitstream.",
        "    // INITVAL is synthetic (ramp / 0xDEAD) — not real data.",
        "    // Real data is written at runtime by the MCU via SPI.",
        "    //",
        "    // Block classification is derived from net names in the DB.",
        "    // Layout may differ from awto-2000 docs — treat both as",
        "    // provisional until explicitly reconciled.",
        "    //",
        f"    // ADC ring ({adc_label}): write=ADC 75 MHz, read=SPI 0xa4 burst.",
        f"    // AWG table ({awg_label}): write=SPI 0x50 cmd, read=DDS addr → DAC.",
        "    // =========================================================",
        "",
    ]

    def _net(n):
        return rn(n) if n else "NC"

    _ebr_assigned: set[str] = set()

    def _bus_ports(block_buses, role):
        return sorted(block_buses.get(role, {}).items())

    def _vec(pairs, width, default="1'b0"):
        bits = dict(pairs)
        return "{" + ", ".join(
            _net(bits[i]) if i in bits else default
            for i in range(width - 1, -1, -1)
        ) + "}"

    def _emit_block(block, kind):
        b = buses[block]
        c = ctrl[block]
        tag = block.lower().replace("r", "r").replace("c", "c")  # R6C20 → r6c20

        wdata_pairs = _bus_ports(b, "write_data")
        rdata_pairs = _bus_ports(b, "read_data")
        waddr_pairs = _bus_ports(b, "write_addr")
        raddr_pairs = _bus_ports(b, "read_addr")

        wdw = (max(i for i, _ in wdata_pairs) + 1) if wdata_pairs else 1
        rdw = (max(i for i, _ in rdata_pairs) + 1) if rdata_pairs else 1
        raw = (max(i for i, _ in raddr_pairs) + 1) if raddr_pairs else 1
        dep = 1 << raw

        wclk = _net(c.get("JCLK0"))
        rclk = _net(c.get("JCLK3"))
        lsr  = _net(c.get("JLSR0") or c.get("JLSR1"))

        if kind == "awg":
            dead = ((1 << wdw) - 1) & 0xDEAD
            init_line = f"            ebr_{tag}_mem[_ebr_{tag}_i] = {wdw}'h{dead:X};  // 0xDEAD truncated to width"
            kind_comment = "AWG waveform table — write: SPI 0x50 cmd  read: DDS addr → DAC"
        elif kind == "adc":
            init_line = f"            ebr_{tag}_mem[_ebr_{tag}_i] = _ebr_{tag}_i[{wdw-1}:0];  // ramp"
            kind_comment = "ADC ring buffer — write: ADC data  read: SPI 0xa4 burst"
        else:
            init_line = f"            ebr_{tag}_mem[_ebr_{tag}_i] = {wdw}'h0;  // unknown block"
            kind_comment = "Unknown EBR block — classification pending"

        out = [
            f"    // --- EBR {block}: {kind_comment} ---",
            f"    // Write clock: {wclk}  Read clock: {rclk}",
            f"    // {dep}-entry × {wdw}-bit  (DB-visible address bits: {raw})",
            f"    reg [{wdw-1}:0] ebr_{tag}_mem [0:{dep-1}];",
            f"    integer _ebr_{tag}_i;",
            f"    initial begin",
            f"        for (_ebr_{tag}_i = 0; _ebr_{tag}_i < {dep}; _ebr_{tag}_i = _ebr_{tag}_i + 1)",
            f"            {init_line}",
            f"    end",
        ]

        # Write port
        waddr_e = _vec(waddr_pairs, raw)
        wdata_e = _vec(wdata_pairs, wdw)
        if lsr and lsr not in ("NC", "1'b0", "1'b1"):
            out += [
                f"    always @(posedge {wclk}) begin",
                f"        if (!{lsr})",
                f"            ebr_{tag}_mem[{waddr_e}] <= {wdata_e};",
                f"    end",
            ]
        else:
            out += [
                f"    always @(posedge {wclk})",
                f"        ebr_{tag}_mem[{waddr_e}] <= {wdata_e};",
            ]

        # Read port
        raddr_e = _vec(raddr_pairs, raw)
        out += [
            f"    reg [{rdw-1}:0] ebr_{tag}_dout;",
            f"    always @(posedge {rclk})",
            f"        ebr_{tag}_dout <= ebr_{tag}_mem[{raddr_e}];",
        ]
        lut_driven = data.get("lut_driven_net_ids", set())
        ff_q_wires = data.get("ff_q_all_wire_ids", set())
        for bit_idx, net in rdata_pairs:
            net_expr = _net(net)
            if net_expr not in ("NC", "1'b0", "1'b1") and net_expr not in _ebr_assigned:
                if net_expr in lut_driven:
                    # LUT buffering stage already drives this net; skip to avoid conflict.
                    out.append(f"    // {net_expr}[{bit_idx}] driven by LUT path from {block}")
                elif net_expr in ff_q_wires:
                    # FF always block drives this net; EBR assign would conflict.
                    out.append(f"    // {net_expr}[{bit_idx}] also FF Q from {block} — FF path takes precedence")
                else:
                    out.append(f"    assign {net_expr} = ebr_{tag}_dout[{bit_idx}];")
                _ebr_assigned.add(net_expr)
            elif net_expr in _ebr_assigned:
                out.append(f"    // {net_expr}[{bit_idx}] also from {block} — shared bus, first driver wins")
        out.append("")
        return out

    # Emit AWG first, then ADC, then unknown
    if awg_blocks:
        lines += [f"    // AWG waveform table block(s): {awg_label}", ""]
    for block in awg_blocks:
        lines += _emit_block(block, "awg")

    if adc_blocks:
        lines += [
            f"    // ADC ring buffer block(s): {adc_label}",
            "    // Shared write-address bus: ebr_waddr_* nets.",
            "    // Shared read-address bus:  ebr_raddr_* nets.",
            "",
        ]
    for block in adc_blocks:
        lines += _emit_block(block, "adc")

    for block in unk_blocks:
        lines += _emit_block(block, "unknown")

    return lines


def emit_footer() -> list[str]:
    """End the module."""
    return ["endmodule", ""]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--bitstream", default="V07",
                    help="Bitstream label to emit (default: V07)")
    ap.add_argument("--out",       default=None,
                    help="Output file path (default: tmp/<bitstream>.v)")
    ap.add_argument("--top",       default="top",
                    help="Verilog module name (default: top)")
    args = ap.parse_args()

    with engine().connect() as conn:
        row = conn.execute(
            text("SELECT id FROM bitstreams WHERE label=:label"),
            {"label": args.bitstream},
        ).fetchone()
        if not row:
            die(f"Bitstream {args.bitstream!r} not found in DB — run load.py first")
        bs_id = row[0]
        data = load_data(conn, bs_id)

    # Assemble all sections
    sections = [
        emit_header(data, args.top),
        emit_ports(data, args.top),
        emit_wires(data),
        emit_efb_comment(data),
        emit_clock_comment(data),
        emit_luts(data),
        emit_ffs(data),
        emit_trigger_comment(data),
        emit_ebr(data),
        emit_unresolved_pads_comment(data),
        emit_footer(),
    ]

    lines = []
    for section in sections:
        lines.extend(section)

    output = "\n".join(lines)

    if args.out is None:
        args.out = f"tmp/{args.bitstream}.v"
    if args.out:
        import subprocess
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        n_named_nets  = len(data["net_name_map"])
        n_named_cells = len(data["cell_name_map"])
        n_total_nets  = len(data["all_nets"])
        n_total_cells = len(data["ffs"]) + len(data["luts"])
        print(
            f"Wrote {out_path}  "
            f"({len(lines)} lines, "
            f"nets {n_named_nets}/{n_total_nets} named, "
            f"cells {n_named_cells}/{n_total_cells} named)"
        )
        # Lint with iverilog if available
        iverilog = subprocess.run(["which", "iverilog"], capture_output=True)
        if iverilog.returncode == 0:
            result = subprocess.run(
                ["iverilog", "-Wall", "-g2012", "-t", "null", str(out_path)],
                capture_output=True, text=True
            )
            msgs = (result.stdout + result.stderr).strip()
            if msgs:
                n_err = sum(1 for l in msgs.splitlines() if "error:" in l)
                n_warn = sum(1 for l in msgs.splitlines() if "warning:" in l)
                print(f"iverilog: {n_err} errors, {n_warn} warnings")
                print(msgs)
            else:
                print("iverilog: OK (0 errors, 0 warnings)")

        # Yosys elaboration: counts surviving logic after constant folding.
        # Most FFs optimise away (d=0) — surviving cells are the real fabric logic.
        # NOTE: EBR/PLL hard IP not visible to Yosys — cell count is expected to be tiny.
        yosys = subprocess.run(["which", "yosys"], capture_output=True)
        if yosys.returncode == 0:
            yosys_script = "read_verilog -sv {v}; proc; opt; stat".format(v=out_path)
            result = subprocess.run(
                ["yosys", "-p", yosys_script],
                capture_output=True, text=True
            )
            combined = result.stdout + result.stderr
            # Extract stat block (between "=== <module> ===" and "End of script")
            in_stat = False
            stat_lines = []
            for line in combined.splitlines():
                if re.match(r"\s*===\s+\S+\s+===", line):
                    in_stat = True
                if "End of script" in line:
                    in_stat = False
                if in_stat:
                    stat_lines.append(line)
            if stat_lines:
                print("yosys (post-opt, EBR/PLL not visible):")
                for l in stat_lines:
                    if l.strip():
                        print(" ", l)
            else:
                yosys_errors = [l for l in combined.splitlines() if "ERROR" in l or "error" in l.lower()]
                if yosys_errors:
                    print("yosys ERROR:")
                    for l in yosys_errors[:5]:
                        print(" ", l)
    else:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")


if __name__ == "__main__":
    main()
