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

    Replaces apostrophes and spaces with underscores.  Prepends 'n_' if the
    first character is a digit (Verilog identifiers must start with a letter
    or underscore).
    """
    ident = re.sub(r"['\s]", "_", raw)
    if ident and ident[0].isdigit():
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


def resolve_cell(cell: str, cell_name_map: dict,
                 cell_clkname_map: dict | None = None) -> str:
    """Return a Verilog identifier for *cell*, preferring the human name.

    Fallback order:
    1. TSV-assigned human name from cell_name_map
    2. Clock-derived name: <short_clk>__<tile_slice>  (if cell_clkname_map provided)
    3. Synthetic cell identifier (reg_rXcY_slice)
    """
    human = cell_name_map.get(cell)
    if human:
        return _sanitise(human)
    if cell_clkname_map:
        clk = cell_clkname_map.get(cell)
        if clk:
            # Strip clk_ prefix for brevity: clk_h2_spi_ser_a → spi_ser_a
            short = re.sub(r"^clk_h\d+_", "", clk)
            # cell is e.g. ff_r10c11_A0 → take the tile+slice suffix
            suffix = re.sub(r"^ff_", "", cell)   # r10c11_A0
            return _sanitise(f"{short}__{suffix}")
    return _sanitise(cell)


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

    # Net names: net → (name, description)
    net_name_rows = q("SELECT net, name, description FROM net_names WHERE bitstream=:bs_id")
    net_name_map = {net: name for net, name, _desc in net_name_rows}
    net_desc_map = {net: desc for net, _name, desc in net_name_rows if desc}

    # Cell names: cell → (name, description)
    cell_name_rows = q("SELECT cell, name, description FROM cell_names WHERE bitstream=:bs_id")
    cell_name_map  = {cell: name for cell, name, _desc in cell_name_rows}

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

    # Build clock-derived cell name map: cell → resolved clock name (for unnamed FFs)
    # Used by emit_ffs and emit_wires to give unnamed FF regs a clock-prefixed name.
    # Only populated when the clock net itself has a human name (not a bare nNNNN).
    cell_clkname_map: dict[str, str] = {}
    for cell, clk, _ce, _d, _q, _lsr in ffs:
        if clk and cell not in cell_name_map:
            clk_human = net_name_map.get(clk)
            if clk_human:
                cell_clkname_map[cell] = clk_human

    # Build FF Q→cell map for wire naming: net → cell (so emit_wires can name Q wires)
    ff_q_cell_map: dict[str, str] = {q: cell for cell, _clk, _ce, _d, q, _lsr in ffs if q}

    return {
        "ffs":              ffs,
        "luts":             luts,
        "pads":             pads,
        "efb_ports":        efb_ports,
        "net_name_map":     net_name_map,
        "net_desc_map":     net_desc_map,
        "cell_name_map":    cell_name_map,
        "cell_clkname_map": cell_clkname_map,
        "ff_q_cell_map":    ff_q_cell_map,
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

    # Resolved ports
    if resolved:
        lines.append(f"    // Physical pads — resolved ({len(resolved)})")
    for i, (pin, label, direction, net_in, net_out) in enumerate(resolved):
        fabric_net = net_in if direction == "in" else net_out
        if direction == "bidir":
            # For bidir we show both; pick net_in if available, else net_out
            fabric_net = net_in or net_out
        direction_kw = {"in": "input  wire", "out": "output wire", "bidir": "inout  wire"}[direction]
        port_name = _sanitise(label)
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

    # Build set of port nets (already declared in module ports)
    port_nets: set[str] = set()
    for _pin, _label, direction, net_in, net_out in pads:
        if direction not in ("in", "out", "bidir"):
            continue
        if net_in is None and net_out is None:
            continue
        if net_in:
            port_nets.add(net_in)
        if net_out:
            port_nets.add(net_out)

    def _wire_name(net: str) -> str:
        """Resolve net to a Verilog wire identifier, with clock-derived fallback."""
        if net in net_name_map:
            return _sanitise(net_name_map[net])
        if net in const_net_map:
            return _sanitise(net)
        # Unnamed net — if it's the Q output of a FF whose clock is named, derive name
        src_cell = ff_q_cell_map.get(net)
        if src_cell:
            # Try TSV cell name first
            cell_human = cell_name_map.get(src_cell)
            if cell_human:
                return _sanitise(f"{cell_human}_q")
            # Fall back to clock-derived: spi_ser_a__r10c11_A0_q
            clk_name = cell_clkname_map.get(src_cell)
            if clk_name:
                short = re.sub(r"^clk_h\d+_", "", clk_name)
                suffix = re.sub(r"^ff_", "", src_cell)
                return _sanitise(f"{short}__{suffix}_q")
        return resolve_net(net, net_name_map, const_net_map)

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

    # Split into three groups, skip port nets and consts handled separately
    named_nets   = []   # have TSV name
    clkderiv_nets = []  # unnamed but Q of a FF with named clock → derived name
    unnamed_nets = []   # truly unnamed
    const_nets   = []
    for net in all_nets:
        if net in port_nets:
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


def _lut_init_to_case(init: str, z_name: str, a: str, b: str, c: str, d: str) -> list[str]:
    """Emit a 4-bit case expression for a LUT with no symbolic fn.

    init is 16 chars of '0'/'1', LSB-first (index 0 = a=0,b=0,c=0,d=0).
    We reverse it to get Verilog's MSB-first bit-select form.
    """
    # Collect which inputs are actually connected
    connected_inputs = []
    for port_name, net_expr in [("d", d), ("c", c), ("b", b), ("a", a)]:
        if net_expr not in ("NC", "1'b0", "1'b1"):
            connected_inputs.append(net_expr)
        else:
            connected_inputs.append(net_expr)

    # Reversed init for Verilog bit-indexing (MSB-first)
    init_msb_first = init[::-1]
    sel_expr = "{" + ", ".join([d, c, b, a]) + "}"

    lines = [f"    assign {z_name} = (16'b{init_msb_first})[{sel_expr}];"]
    return lines


def emit_luts(data: dict) -> list[str]:
    """Emit LUTs as assign statements.

    Structured fn tags (AND, OR, XOR, etc.) become direct boolean expressions.
    COMBO / None → bit-select of the 16-bit init table.
    """
    luts         = data["luts"]
    net_name_map = data["net_name_map"]
    const_net_map = data["const_net_map"]
    cell_name_map = data["cell_name_map"]

    def rn(net):
        return resolve_net(net, net_name_map, const_net_map)

    lines = [
        "    // ── LUTs ──────────────────────────────────────────────────────────────",
        f"    // {len(luts)} LUTs — structured fn → assign expression; COMBO → case bit-select",
    ]

    for cell, init, pa, pb, pc, pd, out_z, fn in luts:
        if out_z is None:
            # Output is not connected to any fabric net — skip
            continue

        z_name    = rn(out_z)
        cell_name = resolve_cell(cell, cell_name_map)
        a_expr = rn(pa)
        b_expr = rn(pb)
        c_expr = rn(pc)
        d_expr = rn(pd)

        if fn is None or fn.startswith("COMBO"):
            # No symbolic simplification — emit bit-select case
            lut_lines = _lut_init_to_case(init, z_name, a_expr, b_expr, c_expr, d_expr)
            lut_lines[-1] += f"  // {cell_name}  init={init}"
            lines.extend(lut_lines)

        elif fn == "CONST0":
            lines.append(f"    assign {z_name} = 1'b0;  // {cell_name} CONST0")

        elif fn == "CONST1":
            lines.append(f"    assign {z_name} = 1'b1;  // {cell_name} CONST1")

        else:
            # Structured fn: substitute port letters with resolved net names.
            # Standalone port letter a/b/c/d → actual Verilog expression.
            port_map = {"a": a_expr, "b": b_expr, "c": c_expr, "d": d_expr}

            def replace_port(m):
                letter = m.group(0)
                expr = port_map.get(letter, letter)
                # Wrap complex expressions in parentheses for clarity
                if " " in expr or "," in expr:
                    return f"({expr})"
                return expr

            vlog_expr = re.sub(r"\b([abcd])\b", replace_port, fn)
            lines.append(f"    assign {z_name} = {vlog_expr};  // {cell_name}")

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
    ffs           = data["ffs"]
    net_name_map  = data["net_name_map"]
    const_net_map = data["const_net_map"]
    cell_name_map = data["cell_name_map"]

    cell_clkname_map = data["cell_clkname_map"]

    def rn(net):
        return resolve_net(net, net_name_map, const_net_map)

    def rc(cell):
        return resolve_cell(cell, cell_name_map, cell_clkname_map)

    # ── Classify each FF ────────────────────────────────────────────────────
    # "stuck": d is '1'b0' and ce is effectively '1'b1' (NULL or literal 1)
    stuck_ffs:  list[tuple] = []   # (cell, clk, ce, d, q, lsr)
    active_ffs: list[tuple] = []

    for row in ffs:
        cell, clk, ce, d, q, lsr = row
        ce_resolved = rn(ce) if ce is not None else "1'b1"
        d_resolved  = rn(d)  if d  is not None else "NC"
        if d_resolved == "1'b0" and ce_resolved == "1'b1":
            stuck_ffs.append(row)
        else:
            active_ffs.append(row)

    lines = [
        "    // ── Flip-flops ─────────────────────────────────────────────────────────",
        f"    // {len(ffs)} total FFs: {len(stuck_ffs)} stuck-at-reset, {len(active_ffs)} active",
    ]

    # ── Reg declarations ────────────────────────────────────────────────────
    for cell, clk, ce, d, q, lsr in ffs:
        cell_ident  = rc(cell)
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

        # Group by (clk, lsr)
        from collections import defaultdict
        stuck_groups: dict[tuple, list] = defaultdict(list)
        for row in stuck_ffs:
            cell, clk, ce, d, q, lsr = row
            clk_expr = rn(clk) if clk else "/* no_clk */"
            lsr_expr = rn(lsr) if lsr else None
            stuck_groups[(clk_expr, lsr_expr)].append(cell)

        for (clk_expr, lsr_expr), cells in sorted(stuck_groups.items()):
            lines.append(f"    // {len(cells)} FFs stuck at 0 on posedge {clk_expr}")
            lines.append(f"    always @(posedge {clk_expr}) begin")
            if lsr_expr and lsr_expr != "1'b0":
                lines.append(f"        if ({lsr_expr}) begin")
                for cell in cells:
                    lines.append(f"            {rc(cell)} <= 1'b0;")
                lines.append("        end else begin")
                for cell in cells:
                    lines.append(f"            {rc(cell)} <= 1'b0;  // d stuck")
                lines.append("        end")
            else:
                for cell in cells:
                    lines.append(f"        {rc(cell)} <= 1'b0;  // d stuck")
            lines.append("    end")
            lines.append("")

    # ── Active FFs ───────────────────────────────────────────────────────────
    if active_ffs:
        lines.append(f"    // ── Active FFs ({len(active_ffs)}) ─────────────────────────────────────────")

        for cell, clk, ce, d, q, lsr in active_ffs:
            cell_ident = rc(cell)
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

    lines.append("")
    return lines


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
                    help="Output file path (default: stdout)")
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
        emit_unresolved_pads_comment(data),
        emit_footer(),
    ]

    lines = []
    for section in sections:
        lines.extend(section)

    output = "\n".join(lines)

    if args.out:
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
    else:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")


if __name__ == "__main__":
    main()
