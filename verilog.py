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
import clocks
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
    # FF dtype map (cell -> dtype string).  MachXO2 FFs store NULL here, so the
    # map is empty and every FF stays on the edge-triggered path (byte-identical).
    # GOWIN latch kinds (DL/DLC/…) are routed to a level-sensitive-latch emitter.
    ff_dtype_map = {cell: dtype for cell, dtype in
                    q("SELECT cell, dtype FROM ffs WHERE bitstream=:bs_id")
                    if dtype}

    # ── MachXO2 clock-spine unification (issue #65) ─────────────────────────
    # A single physical clock routed on one BRANCH_HPBX global track is tapped
    # by many per-region local nets that reachability never unions (the global
    # spine G_VPTXnnnn is a ghost source with no decoded fabric driver), so one
    # physical clock surfaces as N distinct clock-domain nets / ports.  Collapse
    # every clock-domain net that shares the same non-null hpbx_track onto one
    # canonical net (the domain with the most FFs) so the recovered module
    # exposes ONE clock per physical spine.  A BRANCH_HPBX track carries exactly
    # one clock net, so merging within a track is always sound.  hpbx_track is
    # populated only for MachXO2 (GOWIN and other families leave it NULL), so
    # this is inert for every non-MachXO2 recovery.
    # Collapse per-track taps to one canonical clock (shared with report.py so
    # the emitted module and the RE report tell the same 3-clock story).
    clk_unify = clocks.unify_clock_spines(
        q("SELECT clk_net, ff_count, hpbx_track FROM clock_domain_summary "
          "WHERE bitstream=:bs_id"),
        q("SELECT net, name FROM net_names WHERE bitstream=:bs_id"))
    # Original (pre-unification) clock per cell — used for cell/Q-net NAMING so
    # unification never renames a FF's Q wire (which would desync it from the
    # raw-id references emit_ebr/others still use).  Only the always-block clock
    # expression and the clock-port list follow the unified canonical.
    ff_clk_orig: dict[str, str] = {cell: clk for (cell, clk, *_r) in ffs}
    if clk_unify:
        ffs = [(cell, clk_unify.get(clk, clk), ce, d, qn, lsr)
               for (cell, clk, ce, d, qn, lsr) in ffs]

    # LUTs: (cell, init, a, b, c, d, z, fn)
    luts = q("SELECT cell, init, a, b, c, d, z, fn FROM luts WHERE bitstream=:bs_id ORDER BY cell")

    # ALU cells (GOWIN carry/adder) — empty for MachXO2.
    alus = q("SELECT cell, mode, sum_net, cout_net, cin, i0, i1, i3 "
             "FROM alu_cells WHERE bitstream=:bs_id ORDER BY cell")

    # Pad map: (pin, label, direction, net_in, net_out)
    pads = q("SELECT pin, label, direction, net_in, net_out FROM pad_map WHERE bitstream=:bs_id ORDER BY pin")

    # EFB ports: (port_name, net)
    efb_ports = q("SELECT port_name, net FROM efb_ports WHERE bitstream=:bs_id ORDER BY port_name")
    # EFB config: (sel, kind, length, payload) — the 0x72 .efb_block preloads
    # the native decoder recovers (empty on a pre-native/truncated .config).
    efb_config = q("SELECT sel, kind, length, payload FROM efb_config WHERE bitstream=:bs_id ORDER BY sel")

    # EBR buses: (block, bus_role, bit_index, port, net)
    ebr_buses = q("SELECT block, bus_role, bit_index, port, net FROM ebr_buses WHERE bitstream=:bs_id ORDER BY block, bus_role, bit_index")
    # EBR ports: (block, port, role, net)
    ebr_ctrl  = q("SELECT block, port, role, net FROM ebr_ports WHERE bitstream=:bs_id ORDER BY block, port")
    # EBR recovered init (native #54): physical 1024×9 words per block.
    # ebr_init_map[block] = {addr: word9};  a block absent (or all-zero) is a
    # blank/runtime-loaded RAM (e.g. the AWG table, written via SPI cmd 0x50).
    ebr_init_map: dict[str, dict[int, int]] = {}
    for block, addr, word9 in q("SELECT block, addr, word9 FROM ebr_init WHERE bitstream=:bs_id ORDER BY block, addr"):
        ebr_init_map.setdefault(block, {})[addr] = word9
    # ebr_init_blocks: (block, wid, mode, data_width, n_words, n_nonzero)
    ebr_init_blocks = {r.block: r for r in
                       q("SELECT block, wid, mode, data_width, n_words, n_nonzero "
                         "FROM ebr_init_blocks WHERE bitstream=:bs_id")}

    # Net names: net → (name, description, freq_mhz)
    # `spec_` prefix marks every NON-confirmed name as speculative, right in the
    # identifier — only confirmed names (physical pins, OSC/crystal, const nets)
    # stay clean.  So a reader never mistakes an inferred/spatial guess for fact.
    def _spec(name, conf):
        return name if conf == "confirmed" else f"spec_{name}"

    net_name_rows = q("SELECT net, name, description, freq_mhz, confidence FROM net_names WHERE bitstream=:bs_id")
    net_name_map = {net: _spec(name, conf) for net, name, _d, _f, conf in net_name_rows}
    net_desc_map = {net: desc for net, _n, desc, _f, _c in net_name_rows if desc}
    net_freq_map = {net: f for net, _n, _d, f, _c in net_name_rows if f is not None}
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
    cell_name_rows = q("SELECT cell, name, description, confidence FROM cell_names WHERE bitstream=:bs_id")
    cell_name_map  = {cell: _spec(name, conf) for cell, name, _desc, conf in cell_name_rows}
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

    # Name unnamed LUT output nets after their recovered functional cell name
    # (e.g. dpram_r2c11_d0k0), so `assign nXXX = ...` becomes
    # `assign dpram_r2c11_d0k0 = ...`.  Only LUTs whose cell carries a real
    # cell_names entry get named — un-recognised LUTs (no tag) stay nXXX, and
    # constants/already-named nets are left alone.  DPRAM tiles are extracted
    # as both dpram_* and lut_* cells sharing one output net; the query is
    # ORDER BY cell, so dpram_* is seen first and wins.
    # The LUT cell id is already the functional name (dpram_rXcY_dNkM for
    # distributed-RAM data bits, lut_rXcY_Sk for generic LUTs).  A DPRAM tile is
    # extracted as BOTH a dpram_* and a lut_* cell sharing one output net; the
    # query is ORDER BY cell so dpram_* is seen first and wins.
    _existing_net_names = set(net_name_map.values())
    for _cell, _i, _a, _b, _c, _d, _outz, _fn in luts:
        if _outz is None or _outz in net_name_map or _outz in const_net_map:
            continue
        _cname = resolve_cell(_cell, cell_name_map)   # human name, else the cell id
        if not _cname or _SYNTHETIC_NAME_RE.match(_cname):
            continue
        _nm = _cname if _cname not in _existing_net_names else f"{_cname}_{_outz}"
        net_name_map[_outz] = _nm
        _existing_net_names.add(_nm)

    # Net stats: net → (fanout, fanin, is_clock, is_const, is_boundary)
    net_stat_rows = q("SELECT net, fanout, fanin, is_clock, is_const, is_boundary FROM net_stats WHERE bitstream=:bs_id")
    net_stats_map = {
        net: {"fanout": fanout, "fanin": fanin,
              "is_clock": is_clk, "is_const": is_const, "is_boundary": is_bnd}
        for net, fanout, fanin, is_clk, is_const, is_bnd in net_stat_rows
    }

    # For undriven nets, remember the physical wire they sit on (from the arcs)
    # so the emitter can name their ROLE — clock branch / global / DCC output —
    # instead of the misleading "floating?".  Prefer a clock/spine wire when a
    # net touches several.  These nets are driven off-fabric by clock hard IP
    # (PLL/OSC/DCC); see the hard-IP-sim-models issue.
    net_wire_map: dict[str, str] = {}
    for _sn, _sw in q("SELECT sink_net, sink_wire FROM arcs "
                      "WHERE bitstream=:bs_id AND sink_net IS NOT NULL"):
        if not _sw:
            continue
        _cur = net_wire_map.get(_sn)
        _pref = _sw.startswith(("BRANCH", "G_", "CLK"))
        if _cur is None or (_pref and not _cur.startswith(("BRANCH", "G_", "CLK"))):
            net_wire_map[_sn] = _sw

    def _net_role(net: str) -> str:
        w = net_wire_map.get(net, "")
        if w.startswith("BRANCH_HPBX"):
            return "clock branch (HPBX spine) — driven by clock hard IP"
        if "_DCC" in w:
            return "DCC (dynamic clock control) output — clock hard IP"
        if w.startswith(("CLK", "G_")) or "PCLK" in w:
            return f"clock/global spine ({w}) — driven by PLL/OSC/DCC hard IP"
        if w:
            return f"on routing wire {w} — no fabric driver"
        return "no fabric driver"

    net_role_map = {}   # only for undriven nets (fanin==0)
    for net, st in net_stats_map.items():
        if st.get("fanin", 1) == 0:
            net_role_map[net] = _net_role(net)

    # Clock domains: clk_net → [ff_cell, ...]
    # Apply the MachXO2 clock-spine unification (issue #65) so all FFs on one
    # physical spine collapse into a single domain (→ one clock port below).
    clk_domain_rows = q("SELECT clk_net, ff_cell FROM clock_domains WHERE bitstream=:bs_id")
    clock_domains: dict[str, list[str]] = {}
    for clk_net, ff_cell in clk_domain_rows:
        clock_domains.setdefault(clk_unify.get(clk_net, clk_net), []).append(ff_cell)

    # All nets
    all_nets = [row[0] for row in q("SELECT name FROM nets WHERE bitstream=:bs_id ORDER BY name")]

    # Bitstream label / device / package
    meta = q("SELECT label, device, package FROM bitstreams WHERE id=:bs_id")[0]

    # Build clock-derived cell name map: cell → resolved clock name.
    # Populated for ALL FFs (not just unnamed) when the clock has a human name.
    # Used by resolve_cell to prefer clock-domain names over synthetic reg_rNcN names.
    cell_clkname_map: dict[str, str] = {}
    for cell, _clk, _ce, _d, _q, _lsr in ffs:
        clk = ff_clk_orig.get(cell)   # ORIGINAL clock — keeps cell/Q naming stable
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
    _is_gowin = str(meta[1] or "").upper().startswith("GW")
    ff_q_wire_map: dict[str, str] = {}
    for cell, _clk, _ce, _d, q, _lsr in ffs:
        if q is None:
            continue
        q_human = net_name_map.get(q)
        if q_human:
            ff_q_wire_map[cell] = _sanitise(q_human)
        elif cell in cell_name_map:
            ff_q_wire_map[cell] = _sanitise(f"{cell_name_map[cell]}_q")
        elif _is_gowin:
            # GOWIN runs without the MachXO2 auto-naming passes, so most Q nets
            # have no human name.  Connect the FF/latch Q to the fabric anyway,
            # using the RAW net identifier — the same one every reader (LUT
            # inputs, FF D/control) resolves it to, and the one emit_wires
            # declares it under for gowin (its clock-derived Q-wire aliasing is
            # disabled for gowin to keep declarations and references in step).
            rq = resolve_net(q, net_name_map, const_net_map)
            if not rq.startswith("1'b"):
                ff_q_wire_map[cell] = _sanitise(rq)

    # Module port names (sanitised pad labels) — reg declarations must avoid these names
    # because ports are declared as wires in the module header.
    port_names: set[str] = {
        _sanitise(label)
        for _pin, label, direction, _ni, _no in pads
        if direction in ("in", "out", "bidir") and label
    }
    # OUTPUT port names: a FF/LUT that drives an output port's net must keep its
    # connect-assign (`assign <PORT> = <driver>`) — for input/bidir ports the
    # assign is suppressed (the pad drives the fabric), but an output IS driven
    # from fabric, so suppressing it leaves the output dangling (#58).
    output_port_names: set[str] = {
        _sanitise(label)
        for _pin, label, direction, _ni, _no in pads
        if direction == "out" and label
    }
    # INPUT port names: driven externally by the pad.  Nothing in-fabric may
    # drive them — an EBR read-data / LUT / FF assign onto an input-pad net is a
    # multi-driver conflict (yosys warns; Diamond LSE hard-errors).
    input_port_names: set[str] = {
        _sanitise(label)
        for _pin, label, direction, _ni, _no in pads
        if direction in ("in", "bidir") and label
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

    # Clock nets that clock FFs but are not driven by a physical pad become
    # top-level clock INPUT ports: in a fabric-only recovery the clock spine is
    # driven off-fabric by PLL/OSC/DCC hard IP, so from the module's view the
    # clocks are external stimulus.  Promoting them (vs leaving undriven
    # internal wires) makes the recovered module drivable/simulatable.
    pad_nets: set[str] = set()
    for _pin, _label, _dir, net_in, net_out in pads:
        if net_in:
            pad_nets.add(net_in)
        if net_out:
            pad_nets.add(net_out)
    clock_input_nets: set[str] = {
        clk for clk in clock_domains
        if clk and clk not in pad_nets and clk not in const_net_map
    }

    return {
        "ffs":              ffs,
        "luts":             luts,
        "alus":             alus,
        "pads":             pads,
        "efb_ports":        efb_ports,
        "efb_config":       efb_config,
        "clock_input_nets": clock_input_nets,
        "clk_unify":        clk_unify,
        "ebr_buses":        ebr_buses,
        "ebr_ctrl":         ebr_ctrl,
        "ebr_init_map":     ebr_init_map,
        "ebr_init_blocks":  ebr_init_blocks,
        "net_name_map":     net_name_map,
        "net_desc_map":     net_desc_map,
        "net_freq_map":     net_freq_map,
        "cell_name_map":    cell_name_map,
        "cell_clkname_map": cell_clkname_map,
        "ff_q_cell_map":    ff_q_cell_map,
        "ff_q_wire_map":        ff_q_wire_map,
        "port_names":           port_names,
        "output_port_names":    output_port_names,
        "input_port_names":     input_port_names,
        "dual_driven_q_wires":  dual_driven_q_wires,
        "lut_driven_net_ids":   lut_driven_net_ids,
        "ff_q_all_wire_ids":    ff_q_all_wire_ids,
        "const_net_map":    const_net_map,
        "net_stats_map":    net_stats_map,
        "net_role_map":     net_role_map,
        "clock_domains":    clock_domains,
        "all_nets":         all_nets,
        "bs_label":         meta[0],
        "device":           meta[1],
        "package":          meta[2],
        # Family flag — GOWIN devices are GW1N-*/GW2A-*/…  Emitter changes that
        # would perturb the byte-identical MachXO2 output are gated on this.
        "is_gowin":         str(meta[1] or "").upper().startswith("GW"),
        "ff_dtype_map":     ff_dtype_map,
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

    from datetime import datetime
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        f"// Pluribus structural Verilog — {label} ({device} {package})",
        f"// Generated by verilog.py at {ts} — DO NOT EDIT (regenerated on every build)",
        f"// Named nets: {n_named_nets}/{n_total_nets}  "
        f"Named cells: {n_named_cells}/{n_total_cells}",
        "// Cold run: all unnamed objects use synthetic identifiers",
    ]
    # Optional board-provided header note (board-specific context belongs to
    # the board, NOT this generic emitter).  Passed via --header-note; each
    # line is emitted as a comment.  This replaces the old hardcoded
    # single-board calibration warning, which was wrong for other labels.
    note = data.get("header_note")
    if note:
        lines.append("//")
        for ln in note:
            lines.append(f"// {ln}" if ln.strip() else "//")
    lines += ["", "`timescale 1ns/1ps", ""]
    return lines


def emit_ports(data: dict, top_name: str) -> list[str]:
    """Module declaration with port list.

    Resolved pads become actual ports (input/output/inout).
    Unresolved pads are listed as comments at the end of the port list.
    """
    net_name_map = data["net_name_map"]
    const_net_map = data["const_net_map"]
    pads = data["pads"]
    clock_input_nets = data.get("clock_input_nets", set())
    clock_domains = data.get("clock_domains", {})

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

    seen_port_names: set[str] = set()

    # Build the ordered port entries (decl, comment): resolved pads, then clocks.
    pad_entries: list[tuple[str, str]] = []
    for pin, label, direction, net_in, net_out in resolved:
        fabric_net = net_in if direction == "in" else net_out
        if direction == "bidir":
            fabric_net = net_in or net_out
        direction_kw = {"in": "input  wire", "out": "output wire", "bidir": "inout  wire"}[direction]
        base_name = _sanitise(label)
        if base_name == "_" or base_name in seen_port_names:
            port_name = f"pin{pin}"
        else:
            port_name = base_name
        seen_port_names.add(port_name)
        pad_entries.append((f"{direction_kw} {port_name}", f"pin {pin}  net {fabric_net}"))

    # Clock inputs: off-fabric PLL/OSC/DCC clock spine → external stimulus.
    clk_entries: list[tuple[str, str]] = []
    for clk_net in sorted(clock_input_nets):
        name = _sanitise(resolve_net(clk_net, net_name_map, const_net_map))
        if name in seen_port_names:
            continue
        seen_port_names.add(name)
        n_ff = len(clock_domains.get(clk_net, []))
        clk_entries.append((f"input  wire {name}",
                            f"clock — {n_ff} FFs (off-fabric PLL/OSC/DCC; drive from testbench)"))

    n_ports = len(pad_entries) + len(clk_entries)
    idx = 0

    def _port_line(decl, comment):
        nonlocal idx
        idx += 1
        comma = "," if idx < n_ports else ""
        return f"    {decl}{comma}   // {comment}"

    lines = [f"module {top_name} ("]
    if pad_entries:
        lines.append(f"    // Physical pads — resolved ({len(pad_entries)})")
    for decl, comment in pad_entries:
        lines.append(_port_line(decl, comment))
    if clk_entries:
        lines.append(f"    // Clock inputs — {len(clk_entries)} (clock spine, off-fabric hard IP)")
    for decl, comment in clk_entries:
        lines.append(_port_line(decl, comment))

    # Unresolved pads — comment block (not ports)
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
    net_freq_map      = data["net_freq_map"]
    const_net_map     = data["const_net_map"]
    net_stats_map     = data["net_stats_map"]
    net_role_map      = data["net_role_map"]
    cell_clkname_map  = data["cell_clkname_map"]
    ff_q_cell_map     = data["ff_q_cell_map"]
    cell_name_map     = data["cell_name_map"]
    pads              = data["pads"]
    all_nets          = data["all_nets"]
    is_gowin          = data.get("is_gowin", False)

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
        if direction in ("out", "bidir"):
            # Output/bidir pad: net_out is the (unused) boundary net; net_in is
            # the INTERNAL fabric net driving/connecting the pad (#58) and can
            # also feed fabric logic (LUT inputs) — it must stay a declared wire
            # so those references resolve (a bidir net_in that fed a LUT was
            # emitted undeclared → an implicit-net lint error).
            if net_out:
                port_nets.add(net_out)
        else:
            if net_in:
                port_nets.add(net_in)
            if net_out:
                port_nets.add(net_out)
        port_names.add(_sanitise(_label))

    # Clock nets promoted to input ports by emit_ports — exclude from the
    # internal wire declarations so they are ports, not undriven wires.
    for clk_net in data.get("clock_input_nets", set()):
        port_nets.add(clk_net)
        port_names.add(_sanitise(resolve_net(clk_net, net_name_map, const_net_map)))

    # MachXO2 clock-spine unification (issue #65): clock-domain nets merged onto
    # a canonical spine net are driven from that single clock port via an alias
    # (below), so keep them out of the normal wire-declaration categories.
    clk_unify: dict[str, str] = data.get("clk_unify", {})

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
            # The clock-derived Q-wire alias is a MachXO2 nicety: readers there
            # resolve the Q net to its auto-named identifier, which matches.  For
            # gowin the Q nets stay unnamed, so a clock-derived wire name would
            # not match how LUT/FF readers resolve the net (raw n<k>) → keep the
            # raw name for gowin so declarations and references agree.
            if not is_gowin:
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
    isolated_nets = []   # no driver AND no reader — connect to nothing
    for net in all_nets:
        if net in port_nets:
            continue
        if net in clk_unify:
            continue
        if _wire_name(net) in port_names:
            continue
        # A recovered net with no driver AND no reader connects to nothing.
        # Keep it (for traceability) but segregate it to an "isolated" block at
        # the end rather than cluttering the main body.  Named/const nets are
        # never segregated (they carry deliberate annotation).
        st = net_stats_map.get(net, {})
        if (st.get("fanin", 1) == 0 and st.get("fanout", 1) == 0
                and net not in const_net_map and net not in net_name_map):
            isolated_nets.append(net)
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
            freq = net_freq_map.get(net)
            if freq is not None:
                comment_parts.append(f"{freq:g} MHz")
        elif net in ff_q_cell_map:
            src = ff_q_cell_map[net]
            clk = cell_clkname_map.get(src, "?")
            comment_parts.append(f"Q output of {src}  clk={clk}")
        else:
            comment_parts.append("(unnamed)")
        if stats.get("is_clock"):
            comment_parts.append("clock spine (hard IP source)")
        elif (stats.get("fanin", 1) == 0
              and net not in net_name_map and net not in ff_q_cell_map):
            # UNNAMED, read but undriven-in-fabric: name the clock/spine role
            # from its routing wire rather than the misleading "floating?".
            # (Named nets already carry a description, so don't append here.)
            comment_parts.append(net_role_map.get(net, "no fabric driver"))
        comment = "  // " + " — ".join(comment_parts) if comment_parts else ""
        return f"    wire {wire_name};{comment}"

    # Sort named by human name; constants + clock-derived by wire name; unnamed numerically
    named_nets.sort(key=lambda n: net_name_map[n])
    const_nets.sort(key=lambda n: _wire_name(n))
    clkderiv_nets.sort(key=lambda n: _wire_name(n))
    def _net_sort_key(n):
        if n.startswith("n") and n[1:].isdigit():
            return (0, int(n[1:]))
        return (1, n)
    unnamed_nets.sort(key=_net_sort_key)
    isolated_nets.sort(key=_net_sort_key)

    lines = [
        "    // ── Wire declarations ─────────────────────────────────────────────────",
        f"    // {len(named_nets)} named  {len(clkderiv_nets)} clock-derived"
        f"  {len(unnamed_nets)} unnamed  {len(const_nets)} const"
        f"  {len(isolated_nets)} isolated (end)",
    ]

    # NC (not-connected) sentinel — LUT inputs left unconnected are tied to GND.
    lines.append("    wire NC = 1'b0;  // unconnected LUT inputs — tied to GND in MachXO2")

    # Clock-spine unification aliases (issue #65): each clock-domain net that was
    # merged onto a canonical spine net is driven from that canonical clock, so
    # any remaining reference (e.g. an EBR behavioural block clocked on the raw
    # spine net) still sees the single unified clock.  FF always-blocks already
    # use the canonical directly (ffs were remapped in load_data).
    if clk_unify:
        lines.append(
            f"    // Clock-spine unification — {len(clk_unify)} taps aliased to their"
            " canonical clock (issue #65)")
        for net in sorted(clk_unify, key=_net_sort_key):
            canon_name = _sanitise(resolve_net(clk_unify[net], net_name_map, const_net_map))
            lines.append(f"    wire {_wire_name(net)} = {canon_name};")
        lines.append("")

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

    if isolated_nets:
        lines.append(
            f"    // ── Isolated nets ({len(isolated_nets)}) — no driver AND no reader ─")
        lines.append(
            "    // Recovered but connected to nothing in the netlist; kept for"
            " traceability.  (yosys opt_clean -purge removes these.)")
        for net in isolated_nets:
            lines.append(f"    wire {_wire_name(net)};")

    lines.append("")
    return lines


def emit_efb_comment(data: dict) -> list[str]:
    """Comment block describing EFB port connections.

    The EFB is hard IP and cannot be instantiated in plain structural Verilog.
    We document the port→net mapping as comments so a reader can trace signals.
    """
    efb_ports    = data["efb_ports"]
    efb_config   = data.get("efb_config") or []
    net_name_map = data["net_name_map"]
    const_net_map = data["const_net_map"]

    if not efb_ports and not efb_config:
        return []

    lines = [
        "    // ── EFB (embedded function block) ─────────────────────────────────────",
        "    // EFB is hard IP — not instantiable in standard Verilog; a behavioral",
        "    // model is needed to simulate it (see #49).  Recovered config + the",
        "    // port→net mapping are shown below; nets are declared as wires above.",
    ]
    # Recovered 0x72 config block(s): kind (e.g. SPI) is the enabled function.
    for sel, kind, length, payload in efb_config:
        lines.append(f"    //   config: {kind} (sel 0x{sel:02x}, {length} bytes"
                     f" payload {payload})")
    if not efb_config:
        lines.append("    //   config: NONE recovered — .config truncated at cmd 0x72?"
                     " (see #54)")
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

    init: 16-char LSB-first truth table (init[idx] = f(idx), idx = a+2b+4c+8d).
    NOTE: the stored .config INIT is MSB-first (string[k] = f(15-k)); callers
    must reverse it before calling this helper — see _lut_init_to_case. (#63)
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


def _lut_active_positions(init: str) -> set[int]:
    """Index positions (0=a,1=b,2=c,3=d) the truth table actually depends on.

    A position is active iff flipping that input bit changes the output for some
    input combination.  A routed-but-inactive input (e.g. a COMBO3(a,b,c) whose
    D pin is still physically wired) is functionally ignored by the INIT.
    """
    v = int(init, 2)  # MSB-first string → f(p) = (v>>p)&1 (#63)
    active = set()
    for pos in range(4):
        m = 1 << pos
        if any(((v >> p) & 1) != ((v >> (p ^ m)) & 1) for p in range(16)):
            active.add(pos)
    return active


def _lut_init_to_case(init: str, z_name: str, a: str, b: str, c: str, d: str,
                      cell_name: str = "", tie_unused: bool = False) -> list[str]:
    """Emit an assign for a LUT with no structured fn tag.

    First tries _simplify_lut() — for LUTs with ≤2 live inputs this emits a
    direct operator expression (x ^ y, x & y, etc.) instead of a localparam.
    Falls back to a localparam bit-select for more complex truth tables.

    init: 16-char MSB-first truth-table string (string[k] = f(15-k)).  (#63)
    cell_name: human cell name to use for the localparam identifier; empty
               string tells us to use z_name instead (avoids _lut_lut_lut_…).
    tie_unused: when True, index positions the INIT does not actually depend on
               are wired to 1'b0 instead of the (still physically routed) net.
               The function is identical (the table is independent of that bit),
               but it removes the false STRUCTURAL dependency that otherwise makes
               yosys report a combinational loop through a routed-but-unused LUT
               input.  Gated to GOWIN so MachXO2 emission stays byte-identical.
    """
    # _simplify_lut expects LSB-first; the stored INIT is MSB-first, so reverse.
    expr = _simplify_lut(init[::-1], a, b, c, d)
    if expr is not None:
        return [f"    assign {z_name} = {expr};"]

    # Localparam bit-select fallback. init is MSB-first and a Verilog [15:0]
    # localparam literal is written MSB-first, so LP[idx] = f(idx) directly (#63).
    init_msb_first = init
    lp_base = cell_name if cell_name else z_name
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', lp_base)
    # Strip any leading lut_ repetitions to prevent _lut_lut_lut_… prefixes
    sanitized = re.sub(r'^(lut_)+', '', sanitized) or sanitized
    lp_name = f"_lut_{sanitized}"
    sel = [d, c, b, a]  # index bits {d,c,b,a}, positions 3,2,1,0
    if tie_unused:
        active = _lut_active_positions(init)
        sel = [s if pos in active else "1'b0"
               for s, pos in zip(sel, (3, 2, 1, 0))]
    sel_expr = "{" + ", ".join(sel) + "}"

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
    tie_unused   = data.get("is_gowin", False)

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
        # MUX(sel,i0,i1): 3-input LUT mux, sel=0 -> i0, sel=1 -> i1 (see classify_lut).
        (re.compile(r"^MUX\(([abcd]),([abcd]),([abcd])\)$"),
                                                      lambda m: f"({m.group(1)} ? {m.group(3)} : {m.group(2)})"),
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
    # Collect (sort-key, block-lines) per LUT so the emitted assigns can be
    # sorted by output name — related bits (e.g. dpram_r2c11_*) then group.
    blocks: list[tuple[str, list[str]]] = []

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
            blk = _lut_init_to_case(init, z_name, a_expr, b_expr, c_expr, d_expr,
                                    lp_key, tie_unused=tie_unused)
            blk[-1] += f"  // {cell_name}  init={init}"

        elif fn == "CONST0":
            blk = [f"    assign {z_name} = 1'b0;  // {cell_name} CONST0"]

        elif fn == "CONST1":
            blk = [f"    assign {z_name} = 1'b1;  // {cell_name} CONST1"]

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
            # Drop the comment when it just repeats the (now-named) output.
            _cmt = "" if z_name == cell_name else f"  // {cell_name}"
            blk = [f"    assign {z_name} = {vlog_expr};{_cmt}"]

        blocks.append((z_name, blk))
        _assigned_lut_outputs.add(z_name)

    # Emit LUT assigns sorted by output net name so patterns group visually.
    for _z, blk in sorted(blocks, key=lambda kv: kv[0]):
        lines.extend(blk)

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
    output_port_names = data.get("output_port_names", set())
    ff_dtype_map     = data.get("ff_dtype_map", {})

    # GOWIN level-sensitive latch kinds (apycula).  A cell tagged with one of
    # these is a transparent latch, NOT an edge-triggered flop, and is emitted
    # as `always @* if (gate) q = d;` (a state element that legally holds — not a
    # combinational loop).  MachXO2 stores no dtype, so this set is never hit and
    # every FF stays on the byte-identical edge-triggered path.
    _LATCH_KINDS = {"DL", "DLN", "DLC", "DLNC", "DLP", "DLNP"}

    def is_latch(cell: str) -> bool:
        return ff_dtype_map.get(cell) in _LATCH_KINDS

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

        Latches get a distinct `_lat` suffix so they are never vectorised into the
        same reg bus as an edge-triggered flop that shares the tile (which would
        drive one reg from both an edge and a level-sensitive always block).
        """
        return rc(cell) + "_lat" if is_latch(cell) else rc(cell)

    # ── Register vectorisation (#45 phase 2) ────────────────────────────────
    # Collapse per-bit reg ids that share a base and a contiguous numeric
    # suffix into `reg [hi:lo] base` buses.  Only when the char before the
    # trailing digits is a LETTER (a slice/bit suffix like _A0/_A1, _Bk0/_Bk1)
    # — never a coordinate digit — so distinct registers can't be merged.
    # Pure rename of the reg identifier: identical semantics (LEC-equivalent).
    def _split_idx(name):
        m = re.match(r"^(.*[A-Za-z])(\d+)$", name)
        return (m.group(1), int(m.group(2))) if m else (name, None)

    _base_bits: dict[str, set] = {}
    for _c, *_ in ffs:
        _base, _idx = _split_idx(reg_id(_c))
        if _idx is not None:
            _base_bits.setdefault(_base, set()).add(_idx)
    _vec_ref: dict[str, str] = {}      # scalar reg_id -> "base[idx]"
    _vec_bases: dict[str, tuple] = {}  # base -> (hi, lo)
    for _base, _bits in _base_bits.items():
        if len(_bits) < 2:
            continue
        _vec_bases[_base] = (max(_bits), min(_bits))
        for _i in _bits:
            _vec_ref[f"{_base}{_i}"] = f"{_base}[{_i}]"

    def reg_ref(cell: str) -> str:
        """Reg identifier for a WRITE/READ — the vectorised bit when grouped."""
        rid = reg_id(cell)
        return _vec_ref.get(rid, rid)

    # ── Classify each FF ────────────────────────────────────────────────────
    # "stuck"   : d=1'b0, ce=VCC — permanently zero, collapsed into groups
    # "ce_clear": d=1'b0, ce=fabric net — clears to 0 when CE fires, grouped
    # "active"  : d is a real fabric net — emitted individually
    stuck_ffs:    list[tuple] = []   # (cell, clk, ce, d, q, lsr)
    ce_clear_ffs: list[tuple] = []
    active_ffs:   list[tuple] = []
    latch_ffs:    list[tuple] = []   # GOWIN DL/DLC/… transparent latches

    for row in ffs:
        cell, clk, ce, d, q, lsr = row
        if is_latch(cell):
            latch_ffs.append(row)
            continue
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
        f"{len(ce_clear_ffs)} CE-gated-clear, {len(active_ffs)} real-D"
        + (f", {len(latch_ffs)} latch (DL/DLC)" if latch_ffs else ""),
    ]

    # ── Reg declarations ────────────────────────────────────────────────────
    # Multiple FFs can share the same Q net (bus structure); declare each reg
    # only once.  All associated always blocks still write to the shared reg.
    _declared_regs: set[str] = set()
    _n_vec = 0
    for cell, clk, ce, d, q, lsr in ffs:
        cell_ident  = reg_id(cell)
        base, _idx  = _split_idx(cell_ident)
        clk_name    = rn(clk) if clk else "?"
        if cell_ident in _vec_ref:
            # Vectorised: one `reg [hi:lo] base;` per base.
            if base in _declared_regs:
                continue
            _declared_regs.add(base)
            hi, lo = _vec_bases[base]
            _n_vec += 1
            lines.append(f"    reg [{hi}:{lo}] {base} = 0;  // {hi - lo + 1}-bit reg  clk={clk_name}")
            continue
        if cell_ident in _declared_regs:
            continue
        _declared_regs.add(cell_ident)
        human_label = cell_name_map.get(cell, "")
        ce_name     = rn(ce)  if ce  else "1'b1"
        if human_label:
            comment = f"  // {human_label}  clk={clk_name}"
        else:
            ce_part = f"  CE={ce_name}" if ce_name != "1'b1" else ""
            comment = f"  // clk={clk_name}{ce_part}"
        lines.append(f"    reg {cell_ident} = 1'b0;{comment}")
    if _n_vec:
        lines.append(f"    // ({_n_vec} multi-bit registers vectorised into buses)")
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
                lines.append(f"        {reg_ref(cell)} <= 1'b0;")
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
                lines.append(f"            {reg_ref(cell)} <= 1'b0;")
            lines.append("        end")
            lines.append("    end")
            lines.append("")

    # ── Active (real-D) FFs — grouped into one always-block per control set ──
    # Every FF that shares (clk, CE, LSR) is written in ONE always block, in
    # tile/slice order, instead of one block per FF.  This collapses ~1000
    # single-bit always blocks into a few dozen and puts the bits of each
    # register/pipeline stage together.  Pure regrouping — identical semantics
    # (same clk/CE/LSR/D per FF), so it is logically equivalent to the flat
    # form.  True `reg [N:0]` vectorisation (renaming the per-bit regs to a bus)
    # is phase 2 in issue #45.
    if active_ffs:
        from collections import defaultdict as _dd2
        lines.append(f"    // ── Real-D FFs ({len(active_ffs)}) — grouped by (clk, CE, LSR) control set ─")

        act_groups: dict[tuple, list] = _dd2(list)
        for cell, clk, ce, d, q, lsr in active_ffs:
            clk_expr = rn(clk) if clk else "/* no_clk */"
            ce_expr  = rn(ce)  if ce  else "1'b1"
            d_expr   = rn(d)   if d   else "NC"
            lsr_expr = rn(lsr) if lsr else None
            lsr_key  = lsr_expr if (lsr_expr and lsr_expr not in ("1'b0", "NC")) else None
            act_groups[(clk_expr, ce_expr, lsr_key)].append(
                (reg_ref(cell), d_expr, cell_name_map.get(cell, "")))

        for (clk_expr, ce_expr, lsr_key), members in sorted(
                act_groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "")):
            members.sort()  # tile/slice order (reg id encodes r{R}c{C}_{slice})
            ctl = "clk=" + clk_expr
            if ce_expr != "1'b1":
                ctl += f"  CE={ce_expr}"
            if lsr_key:
                ctl += f"  LSR={lsr_key}"
            lines.append(f"    // {len(members)} FFs — {ctl}")
            lines.append(f"    always @(posedge {clk_expr}) begin")
            for reg_ident, d_expr, human in members:
                hc = f"  // {human}" if human else ""
                if lsr_key and ce_expr != "1'b1":
                    lines.append(f"        if ({lsr_key})       {reg_ident} <= 1'b0;")
                    lines.append(f"        else if ({ce_expr})  {reg_ident} <= {d_expr};{hc}")
                elif lsr_key:
                    lines.append(f"        if ({lsr_key}) {reg_ident} <= 1'b0;")
                    lines.append(f"        else          {reg_ident} <= {d_expr};{hc}")
                elif ce_expr != "1'b1":
                    lines.append(f"        if ({ce_expr}) {reg_ident} <= {d_expr};{hc}")
                else:
                    lines.append(f"        {reg_ident} <= {d_expr};{hc}")
            lines.append("    end")
            lines.append("")

    # ── Transparent latches (GOWIN DL/DLC/…) ────────────────────────────────
    # A level-sensitive latch emitted as `always @* if (gate) q = d;`.  yosys
    # models it as a $dlatch (a state element), so a routed-but-held feedback
    # path is a legal latch — NOT the combinational loop a self-feeding assign
    # would create.  Polarity follows the apycula cells_sim.v definitions:
    #   DL:  if (CLK)  DLN: if (!CLK)   +CE: (gate && CE)
    #   *C:  if (CLEAR) q=0; else …     *P: if (PRESET) q=1; else …
    # CLK is the gate G, CE the enable, and the SR wire is the CLEAR/PRESET.
    if latch_ffs:
        lines.append(f"    // ── Transparent latches ({len(latch_ffs)}) — DL/DLC/… level-sensitive ─")
        for cell, clk, ce, d, q, lsr in sorted(latch_ffs, key=lambda r: reg_id(r[0])):
            kind    = ff_dtype_map.get(cell, "DL")
            reg_ident = reg_ref(cell)
            gate    = rn(clk) if clk else "1'b1"
            ce_expr = rn(ce)  if ce  else "1'b1"
            d_expr  = rn(d)   if d   else "1'b0"
            ctrl    = rn(lsr) if lsr else None
            gate_e  = f"!{gate}" if kind.startswith("DLN") else gate
            gate_cond = f"{gate_e} && {ce_expr}" if ce_expr != "1'b1" else gate_e
            human   = cell_name_map.get(cell, "")
            hc      = f"  // {human} {kind}" if human else f"  // {kind}"
            lines.append(f"    always @* begin{hc}")
            if kind.endswith("C") and ctrl and ctrl not in ("1'b0", "NC"):
                lines.append(f"        if ({ctrl})      {reg_ident} = 1'b0;")
                lines.append(f"        else if ({gate_cond}) {reg_ident} = {d_expr};")
            elif kind.endswith("P") and ctrl and ctrl not in ("1'b0", "NC"):
                lines.append(f"        if ({ctrl})      {reg_ident} = 1'b1;")
                lines.append(f"        else if ({gate_cond}) {reg_ident} = {d_expr};")
            else:
                lines.append(f"        if ({gate_cond}) {reg_ident} = {d_expr};")
            lines.append("    end")
        lines.append("")

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
    q_assigns: list[tuple[str, str]] = []
    for cell, _clk, _ce, _d, q, _lsr in ffs:
        if q is None:
            continue
        q_wire = ff_q_wire_map.get(cell)
        if q_wire is None:
            continue
        if q_wire in seen_q_assigns:
            continue
        if q_wire in port_names and q_wire not in output_port_names:
            continue  # input/bidir port: the pad drives the fabric net
        # (output ports fall through: `assign <PORT> = <reg>` drives the output)
        if q_wire in dual_driven:
            continue  # LUT already drives this wire; second assign would conflict
        seen_q_assigns.add(q_wire)
        q_assigns.append((q_wire, reg_ref(cell)))
    # Sorted by the driven net name so the connect block reads alphabetically.
    for q_wire, r in sorted(q_assigns):
        lines.append(f"    assign {q_wire} = {r};  // Q output")
    if q_assigns:
        lines.append("")

    lines.append("")
    return lines


# apycula ALU vendor model (share/yosys/gowin/cells_sim.v):
#   SUM = S ^ CIN ;  COUT = S ? CIN : C  with (S,C) selected by ALU_MODE.
# Emitted inline so the recovered F output (SUM, or COUT for the C2L carry-to-
# logic mode) is DRIVEN by the real arithmetic, and the carry chains through the
# shared CIN nodes.  Values are already resolved net names / constants.
def _alu_sum_carry(mode: str, i0: str, i1: str, i3: str) -> tuple[str, str]:
    m = str(mode)
    return {
        "0": (f"({i0} ^ {i1})", i0),                                   # ADD
        "1": (f"({i0} ^ ~{i1})", i0),                                  # SUB
        "2": (f"({i3} ? ({i0} ^ {i1}) : ({i0} ^ ~{i1}))", i0),        # ADDSUB
        "3": (f"({i0} ^ ~{i1})", "1'b1"),                             # NE
        "4": (f"({i0} ^ ~{i1})", i0),                                  # GE
        "5": (f"(~{i0} ^ {i1})", i1),                                  # LE
        "6": (f"({i0})", "1'b0"),                                      # CUP
        "7": (f"(~{i0})", "1'b1"),                                     # CDN
        "8": (f"({i3} ? {i0} : ~{i0})", i0),                          # CUPCDN
        "9": (f"(({i0} & {i1}) ^ {i3})", f"({i0} & {i1})"),           # MULT
    }.get(m, (f"({i0} ^ {i1})", i0))


def emit_alus(data: dict) -> list[str]:
    """Document the recovered GOWIN ALU (carry/adder) cells.

    Empty for MachXO2 (no alu_cells rows), so this is a no-op there.

    The apycula vendor model is  SUM = S ^ CIN ; COUT = S ? CIN : C  with (S,C)
    selected by ALU_MODE — `_alu_sum_carry` builds those expressions and the
    alu_cells table carries every cell's mode + operand nets.  The outputs are
    NOT driven here on purpose: in ALU mode the slice's A/B/C/D/F wires are fused
    into shared nets by the routing-graph node union (e.g. one bit's SUM output
    and another bit's B input resolve to the same net), so emitting the arithmetic
    on top of those collapsed nets manufactures false combinational loops.
    Separating the ALU-internal wires from the fabric net graph is the remaining
    work; until then the outputs stay undriven (no feedback), and the recovered
    structure lives in the alu_cells table for downstream analysis.
    """
    alus = data.get("alus", [])
    if not alus:
        return []
    from collections import Counter
    modes = Counter(str(mode) for _c, mode, *_ in alus)
    mode_names = {"0": "ADD", "1": "SUB", "2": "ADDSUB", "3": "NE", "4": "GE",
                  "5": "LE", "6": "CUP", "7": "CDN", "8": "CUPCDN", "9": "MULT/C2L"}
    hist = ", ".join(f"{mode_names.get(m, m)}={n}" for m, n in sorted(modes.items()))
    return [
        "    // ── ALU carry/adder cells (recovered, not driven) ───────────────────",
        f"    // {len(alus)} ALU bits recovered into the alu_cells table — modes: {hist}.",
        "    // Vendor model: SUM = S ^ CIN ; COUT = S ? CIN : C  (S,C per ALU_MODE).",
        "    // Outputs left undriven: the slice A/B/C/D/F wires collapse into shared",
        "    // fabric nets under the routing-graph node union, so driving the",
        "    // arithmetic here would fabricate false combinational loops.",
        "",
    ]


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


def _emit_ebr_init(tag: str, init: dict, width: int, depth: int, blank: bool) -> list[str]:
    """Inline `initial` block: zero-fill, then the recovered nonzero words.

    `init` maps physical address → 9-bit word (native #54).  A blank block
    (runtime-loaded, e.g. the AWG table via SPI 0x50) is left zero-filled.
    """
    lines = [
        f"    integer _ebr_{tag}_i;",
        "    initial begin",
        f"        for (_ebr_{tag}_i = 0; _ebr_{tag}_i < {depth}; _ebr_{tag}_i = _ebr_{tag}_i + 1)",
        f"            ebr_{tag}_mem[_ebr_{tag}_i] = {width}'h0;",
    ]
    if not blank:
        hexw = (width + 3) // 4
        items = [(a, v) for a, v in sorted(init.items()) if v]
        per = 6
        for i in range(0, len(items), per):
            chunk = items[i:i + per]
            lines.append("        " + " ".join(
                f"ebr_{tag}_mem[{a}]={width}'h{v:0{hexw}X};" for a, v in chunk))
    lines.append("    end")
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

    lines: list[str] = [
        "",
        "    // =========================================================",
        "    // EBR (Embedded Block RAM) — behavioral models",
        "    // =========================================================",
        "    // WARNING: EBR is hard IP. These behavioral models represent",
        "    // structural connections recovered from the bitstream.",
        "    // INIT is the REAL recovered content (native decode, #54): each",
        "    // block is the physical 1024×9 array with its .bram_init words.",
        "    // A BLANK block carries no bitstream init — it is runtime-loaded",
        "    // by the MCU over SPI (e.g. the AWG table via cmd 0x50).",
        "    //",
        "    // Init presence is authoritative for runtime-vs-preloaded; the",
        "    // net-name kind is a functional hint only.  The fabric routes a",
        "    // subset of the physical address/data bits (bit positions from the",
        "    // DB); the full physical init is retained for reference/simulation.",
        "    // =========================================================",
        "",
    ]

    def _net(n):
        return rn(n) if n else "NC"

    _ebr_assigned: set[str] = set()
    read_ports: list[dict] = []          # for the sim sweep harness (#49 M4)

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

        # Physical EBR: 1024 nine-bit words.  Init presence (not net names)
        # decides runtime-loaded (blank) vs bitstream-preloaded.
        PW, PD = 9, 1024
        PA = (PD - 1).bit_length()          # 10 physical address bits
        init    = data["ebr_init_map"].get(block, {})
        ib      = data["ebr_init_blocks"].get(block)
        nonzero = ib.n_nonzero if ib else 0
        mode    = ib.mode if ib else "?"
        blank   = nonzero == 0

        if blank:
            role = ("AWG waveform table — BLANK: runtime-loaded via SPI 0x50 (DDS → DAC)"
                    if kind == "awg"
                    else "BLANK: runtime-loaded RAM (no bitstream init)")
        else:
            hint = {"awg": "AWG-region ", "adc": "ADC-region "}.get(kind, "")
            role = f"{hint}block — PRELOADED: {nonzero} nonzero words from bitstream"

        out = [
            f"    // --- EBR {block}: {role} ---",
            f"    // Write clock: {wclk}  Read clock: {rclk}   mode {mode}",
            f"    // Physical {PD}×{PW}; fabric routes {raw} read-addr / {wdw} write-data bits.",
            f"    reg [{PW-1}:0] ebr_{tag}_mem [0:{PD-1}];",
        ]
        out += _emit_ebr_init(tag, init, PW, PD, blank)

        # Write port: only routed data bits are written, so unrouted bits
        # (including preloaded init) are preserved.  Full physical address.
        waddr_e = _vec(waddr_pairs, PA)
        wr_body = [f"            ebr_{tag}_mem[{waddr_e}][{bi}] <= {_net(net)};"
                   for bi, net in wdata_pairs if _net(net) != "NC"]
        if not wr_body:
            wr_body = [f"            // no routed write-data bits"]
        if lsr and lsr not in ("NC", "1'b0", "1'b1"):
            out += [f"    always @(posedge {wclk}) begin",
                    f"        if (!{lsr}) begin"] + wr_body + ["        end", "    end"]
        else:
            out += [f"    always @(posedge {wclk}) begin"] + wr_body + ["    end"]

        # Read port
        raddr_e = _vec(raddr_pairs, PA)
        # Record the routed read-address leaf nets so the sim sweep harness
        # (#49 M4) can force a clean address onto them — the fabric read-address
        # generator is partly off-fabric (ghost bits), so left to itself the
        # read index is X in sim.  bit_idx -> rendered leaf net (skip consts).
        raddr_leaves = {i: _net(n) for i, n in raddr_pairs
                        if _net(n) not in ("NC", "1'b0", "1'b1")}
        if raddr_leaves:
            read_ports.append({"tag": tag, "block": block, "rclk": rclk,
                               "pw": PW, "raddr": raddr_leaves})
        out += [
            f"    reg [{PW-1}:0] ebr_{tag}_dout;",
            f"    always @(posedge {rclk})",
            f"        ebr_{tag}_dout <= ebr_{tag}_mem[{raddr_e}];",
        ]
        lut_driven = data.get("lut_driven_net_ids", set())
        ff_q_wires = data.get("ff_q_all_wire_ids", set())
        input_ports = data.get("input_port_names", set())
        for bit_idx, net in rdata_pairs:
            net_expr = _net(net)
            if net_expr not in ("NC", "1'b0", "1'b1") and net_expr not in _ebr_assigned:
                if net_expr in input_ports:
                    # Net is an INPUT pad (driven externally, e.g. an ADC data
                    # line feeding the EBR write port).  Driving it from the EBR
                    # dout is a multi-driver conflict (Diamond LSE hard-errors).
                    out.append(f"    // {net_expr}[{bit_idx}] is an input pad — not driven from {block}")
                elif net_expr in lut_driven:
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

    # Emit blank (runtime-loaded) blocks first, then preloaded — init status
    # is authoritative; _block_kind() is only the functional hint.
    def _nonzero(block):
        ib = data["ebr_init_blocks"].get(block)
        return ib.n_nonzero if ib else 0

    blank_blocks = [b for b in all_blocks if _nonzero(b) == 0]
    loaded_blocks = [b for b in all_blocks if _nonzero(b) > 0]
    if blank_blocks:
        lines += [f"    // Runtime-loaded (blank) block(s): {'/'.join(blank_blocks)}", ""]
    for block in blank_blocks:
        lines += _emit_block(block, _block_kind(block))
    if loaded_blocks:
        lines += [f"    // Bitstream-preloaded block(s): {'/'.join(loaded_blocks)}", ""]
    for block in loaded_blocks:
        lines += _emit_block(block, _block_kind(block))

    data["ebr_read_ports"] = read_ports
    return lines


def emit_output_drives(data: dict) -> list[str]:
    """`assign <output_port> = <fabric driver>;` for output pads (#58).

    pad_map.net_in now carries the fabric net driving each output pad.  Without
    these assigns the output ports are declared but undriven, so the whole
    design looks dead to a synth/sim tool.  Port names replicate emit_ports'
    resolved-pad naming so the assign targets the actual port identifier.
    """
    net_name_map = data["net_name_map"]
    const_net_map = data["const_net_map"]
    net_stats_map = data.get("net_stats_map", {})
    pads = data["pads"]

    resolved = [(pin, label, d, ni, no) for pin, label, d, ni, no in pads
                if d in ("in", "out", "bidir") and (ni is not None or no is not None)]
    seen: set[str] = set()
    assigns: list[str] = []
    for pin, label, direction, net_in, net_out in resolved:
        base = _sanitise(label)
        port = f"pin{pin}" if (base == "_" or base in seen) else base
        seen.add(port)
        if direction != "out" or not net_in:
            continue
        # Skip when the driver is itself undriven (fanin=0): the output is
        # genuinely driven off-fabric, and such a shared ghost net may also be a
        # bidir-pad net excluded from declaration — an assign would dangle.
        if net_stats_map.get(net_in, {}).get("fanin", 1) == 0:
            continue
        driver = resolve_net(net_in, net_name_map, const_net_map)
        if driver in ("NC", "1'b0", "1'b1") or driver == port:
            continue
        assigns.append(f"    assign {port} = {driver};")
    if not assigns:
        return []
    return (["", "    // ── Output pad drivers (#58) — pads driven by fabric logic ──"]
            + sorted(assigns) + [""])


def emit_testbench(data: dict, top_name: str) -> list[str]:
    """Generate a simulation testbench for the recovered module (#49).

    Drives every clock input at its recovered frequency, rolls a ramp across the
    ADC data pads, ties the rest of the inputs low, monitors the output pads,
    and dumps a VCD.  It is a STARTING point: the off-fabric control (the
    spi_efb_* ghost nets) is still internal-undriven, so the datapath won't do
    anything meaningful until the EFB behavioral model drives them.  Port names
    replicate emit_ports so the instantiation binds correctly.
    """
    net_name_map = data["net_name_map"]
    const_net_map = data["const_net_map"]
    pads = data["pads"]
    clock_input_nets = data.get("clock_input_nets", set())
    clock_domains = data.get("clock_domains", {})
    net_freq_map = data.get("net_freq_map", {})

    resolved = [(pin, label, d, ni, no) for pin, label, d, ni, no in pads
                if d in ("in", "out", "bidir") and (ni is not None or no is not None)]
    seen: set[str] = set()
    in_ports: list[str] = []
    adc_ports: list[str] = []
    out_ports: list[str] = []
    bidir_ports: list[str] = []
    for pin, label, direction, ni, no in resolved:
        base = _sanitise(label)
        port = f"pin{pin}" if (base == "_" or base in seen) else base
        seen.add(port)
        if direction == "out":
            out_ports.append(port)
        elif direction == "bidir":
            bidir_ports.append(port)   # inout: wire, left undriven in the TB
        elif port.startswith("ADC_D"):
            adc_ports.append(port)
        else:
            in_ports.append(port)

    clocks: list[tuple[str, float]] = []
    for clk_net in sorted(clock_input_nets):
        name = _sanitise(resolve_net(clk_net, net_name_map, const_net_map))
        if name in seen:
            continue
        seen.add(name)
        clocks.append((name, net_freq_map.get(clk_net) or 125.0))

    all_in = [n for n, _ in clocks] + adc_ports + in_ports
    L = [
        "`timescale 1ns/1ps",
        "",
        f"// Recovered-design testbench for {top_name} (pluribus #49, milestone 1).",
        "// Drives clocks at recovered frequencies + a ramp on the ADC pads.",
        "// The off-fabric control (spi_efb_* ghost nets) is undriven (X) until",
        "// the EFB behavioral model lands, so DAC output is not yet meaningful.",
        f"module {top_name}_tb;",
    ]
    for n, _ in clocks:
        L.append(f"    reg {n} = 1'b0;")
    for n in adc_ports + in_ports:
        L.append(f"    reg {n} = 1'b0;")
    for n in out_ports:
        L.append(f"    wire {n};")
    for n in bidir_ports:
        L.append(f"    wire {n};   // inout — left undriven")
    L.append("")
    L.append(f"    {top_name} dut (")
    conns = [f"        .{n}({n})" for n in all_in + out_ports + bidir_ports]
    L.append(",\n".join(conns))
    L += ["    );", ""]
    for n, f in clocks:
        half = 1000.0 / (2.0 * f)
        L.append(f"    always #{half:.4f} {n} = ~{n};  // {f:g} MHz")
    L.append("")
    if adc_ports:
        drv = clocks[0][0] if clocks else all_in[0]
        L += [
            "    // ADC data: a rolling ramp on the capture inputs.",
            "    reg [7:0] adc_ramp = 8'd0;",
            f"    always @(posedge {drv}) adc_ramp <= adc_ramp + 8'd1;",
        ]
        for i, n in enumerate(adc_ports):
            L.append(f"    always @* {n} = adc_ramp[{i % 8}];")
        L.append("")
    # EBR read-address sweep harness (#49 M4).  The recovered read address is
    # partly off-fabric (ghost bits) + a ghost read-enable, so left to itself
    # the read index is X in closed-loop sim and no block ever streams its
    # prefill.  Here we FORCE a clean incrementing address onto the routed
    # read-address leaf nets (iverilog `force` overrides their fabric drivers)
    # and observe the recovered EBR contents stream out — an end-to-end check
    # that the recovered init + read-port model reproduce the self-test ramp.
    read_ports = data.get("ebr_read_ports") or []
    sweep = data.get("sim_ebr_sweep") and read_ports and clocks
    if sweep:
        drv = clocks[0][0]
        forced: dict[str, int] = {}       # leaf net -> counter bit (first wins)
        for rp in read_ports:
            for i, leaf in rp["raddr"].items():
                forced.setdefault(leaf, i)
        douts = [rp["tag"] for rp in read_ports]
        L += [
            "    // ── EBR read-address sweep (#49 M4): force a clean address ──",
            "    // Overrides the (partly off-fabric) recovered read-address logic",
            "    // so each block's prefilled contents stream out of ebr_*_dout.",
            "    // The forces are RE-APPLIED every cycle: a one-shot `force ... =",
            "    // _ebr_sweep[b]` in an initial block latches the address at t=0",
            "    // instead of tracking the counter (iverilog).",
            "    reg [9:0] _ebr_sweep = 10'd0;",
            f"    always @(posedge {drv}) begin",
            "        _ebr_sweep <= _ebr_sweep + 10'd1;",
        ]
        for leaf, bit in sorted(forced.items(), key=lambda kv: kv[1]):
            L.append(f"        force dut.{leaf} = _ebr_sweep[{bit}];")
        L.append("    end")
        watch = "  ".join(f"{t}=%h" for t in douts)
        args = ", ".join(f"dut.ebr_{t}_dout" for t in douts)
        L += [
            f"    always @(posedge {drv}) if (_ebr_sweep < 10'd48)",
            f'        $display("SWEEP addr=%0d  {watch}", _ebr_sweep, {args});',
            "",
        ]

    L += [
        "    initial begin",
        f'        $dumpfile("{top_name}_tb.vcd");',
        f"        $dumpvars(0, {top_name}_tb);",
    ]
    if out_ports:
        watch = " ".join(f"%b" for _ in out_ports[:8])
        args = ", ".join(out_ports[:8])
        L.append(f'        $monitor("t=%0t  {watch}", $time, {args});')
    L += [
        "        #2000 $finish;   // 2 us",
        "    end",
        "endmodule",
        "",
    ]
    return L


def emit_efb_model(data: dict) -> list[str]:
    """Behavioral EFB SPI-slave stub — a TEMPLATE for simulating the EFB.

    The EFB is hard IP: its behaviour is fixed silicon, not recoverable from the
    bitstream, which yields only its CONFIG (e.g. SPI mode, sel 0x54).  To
    simulate the recovered design a testbench needs a behavioral EFB; this is a
    generic MachXO2 EFB-in-SPI-mode skeleton.  The device-specific command /
    register protocol is left as a TODO and referenced to the board's SPI docs
    (not hardcoded here — the engine stays board-agnostic).

    It is emitted as a SEPARATE module, deliberately NOT auto-instantiated: the
    recovered EFB port→net mapping aliases several ports onto the same
    FF-driven fabric nets, so wiring it in automatically would create driver
    conflicts.  Instantiate it by hand once the port mapping is disambiguated.
    """
    efb_config = data.get("efb_config") or []
    efb_ports  = data.get("efb_ports") or []
    if not efb_config:
        return []
    kind = efb_config[0][1]
    net_name_map = data["net_name_map"]
    const_net_map = data["const_net_map"]

    lines = [
        "",
        "// ═══════════════════════════════════════════════════════════════════",
        f"// EFB behavioral model (TEMPLATE, not auto-wired) — recovered config: {kind}",
        "// ═══════════════════════════════════════════════════════════════════",
        "// Hard IP: behaviour is fixed silicon, only the CONFIG is recovered.",
        "// Fill in the command/register decode from the board SPI protocol docs.",
        "// Recovered fabric-side EFB ports (port <-> net):",
    ]
    for pn, net in efb_ports:
        lines.append(f"//   {pn:<10} <-> {resolve_net(net, net_name_map, const_net_map)}")
    if kind != "SPI":
        lines.append(f"// NOTE: recovered kind is {kind}, not SPI — adapt this stub.")
    lines += [
        "module efb_spi_slave (",
        "    input  wire        spi_sck,   // SPI clock from MCU (mode 0, MSB first)",
        "    input  wire        spi_cs_n,  // chip select, active low (FPGA_nCS / CSSPIN)",
        "    input  wire        spi_mosi,  // MCU -> FPGA",
        "    output reg         spi_miso,  // FPGA -> MCU",
        "    output reg  [7:0]  wb_dato,   // WISHBONE data to fabric (JWBDATO0-7)",
        "    output reg         wb_ack     // JWBACKO",
        ");",
        "    reg [7:0] shreg;   // receive shift register",
        "    reg [2:0] bitcnt;",
        "    reg [7:0] cmd;     // first byte after CS assert = command",
        "    always @(posedge spi_sck or posedge spi_cs_n) begin",
        "        if (spi_cs_n) begin",
        "            bitcnt <= 3'd0;",
        "        end else begin",
        "            shreg  <= {shreg[6:0], spi_mosi};",
        "            bitcnt <= bitcnt + 3'd1;",
        "            if (bitcnt == 3'd7)",
        "                cmd <= {shreg[6:0], spi_mosi};",
        "            // TODO: decode `cmd` per the board SPI protocol (command",
        "            // banks + register map) and drive wb_dato / spi_miso.",
        "        end",
        "    end",
        "endmodule",
        "",
    ]
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
    ap.add_argument("--header-note", default=None,
                    help="Board-specific note file; emitted as header comments")
    ap.add_argument("--tb-out", default=None,
                    help="Also write a simulation testbench to this path (#49)")
    ap.add_argument("--sim-ebr-sweep", action="store_true",
                    help="In the testbench, force a clean incrementing address "
                         "onto each EBR's routed read-address nets so the "
                         "recovered prefill streams out (#49 M4 read-path demo)")
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

    if args.header_note and Path(args.header_note).exists():
        data["header_note"] = Path(args.header_note).read_text(
            encoding="utf-8").splitlines()
    data["sim_ebr_sweep"] = args.sim_ebr_sweep

    # Assemble all sections
    sections = [
        emit_header(data, args.top),
        emit_ports(data, args.top),
        emit_wires(data),
        emit_efb_comment(data),
        emit_clock_comment(data),
        emit_luts(data),
        emit_ffs(data),
        emit_alus(data),
        emit_trigger_comment(data),
        emit_ebr(data),
        emit_output_drives(data),
        emit_unresolved_pads_comment(data),
        emit_footer(),
        emit_efb_model(data),
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
        if args.tb_out:
            tb_path = Path(args.tb_out)
            tb_path.parent.mkdir(parents=True, exist_ok=True)
            tb_path.write_text("\n".join(emit_testbench(data, args.top)), encoding="utf-8")
            print(f"Wrote testbench {tb_path}")
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
