#!/usr/bin/env python3
"""
gen_fuzz_targets.py — generate Diamond fuzz target directories for MachXO2-1200HC TQFP100.

Usage:
    python3 scripts/gen_fuzz_targets.py [--targets-dir PATH] [--list] [--only NAME]

Outputs one directory per fuzz target under fuzz/targets/<name>/ containing:
  fuzz.v   — Verilog instantiating the primitive under test
  fuzz.lpf — LPF constraints (pin assignments)
  run.tcl  — TCL batch flow (PAR + bitgen)
  fuzz.ldf — Diamond project file

Safe bonded pins by bank (TQFP100, not power, not JTAG 90/91/94/95):
  Bank 0 (top):    88,87,86,85,84,83,82,81,80,78,77,76,99,98,97,96
  Bank 1 (right):  74,75,71,70,69,68,67,66,65,64,63,62,61,60,59,58,57,54,53,52,51
  Bank 2 (bottom): 34,35,36,37,38,39,40,41,42,43,45,47,48,49,27,28,29,30,31,32
  Bank 3 (left):   1,2,3,4,7,8,9,10,12,13,14,15,16,17,18,19,20,21,24,25

Pin assignment policy per bank variant:
  Bank 0: clk=88, d=87, d2=86, d3=85, outputs start at 84,83,82,81,80,78,...
  Bank 1: clk=63, d=62, d2=61, d3=60, outputs start at 59,58,57,54,...
  Bank 2: clk=34, d=35, d2=36, d3=37, outputs start at 38,39,40,41,...
"""

from __future__ import annotations
import argparse
import itertools
import os
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------

SCRIPT_DIR  = Path(__file__).resolve().parent          # fuzz/scripts/
FUZZ_DIR    = SCRIPT_DIR.parent                        # fuzz/
TARGETS_DIR = FUZZ_DIR / "targets"

# Strategy file lives two levels above each target dir:  targets/<name>/../../aw21.sty
STY_REL = "../../aw21.sty"

# ---------------------------------------------------------------------------
# Pin tables
# ---------------------------------------------------------------------------

# Per-bank pin pools — first entry is the preferred clock pin, rest are data/output
BANK_PINS = {
    0: [88, 87, 86, 85, 84, 83, 82, 81, 80, 78, 77, 76, 99, 98, 97, 96],
    1: [63, 62, 61, 60, 59, 58, 57, 54, 53, 52, 51, 74, 75, 71, 70, 69],
    2: [34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 45, 47, 48, 49, 27, 28],
}

# LVDS pairs (P, N) per bank
LVDS_PAIRS = {
    # True A/B differential pairs for IDDRX/ODDRX placement.
    # Format: (A_pin, B_pin) — A is the "true" (positive) pad.
    # MachXO2 TQFP100: IDDRX input must be on an A-side pad.
    # Bank 0: row 11 A=88/B=87 — but 88 is our preferred clk pin.
    #         Use row 9: A=97, B=96 (both out-direction in normal use but usable for fuzz).
    # Bank 1: row 5 A=65/B=64. Row 2: A=75/B=74.
    # Bank 2: row mapped per tsv — use row 8 col A=43/B=42.
    0: (97, 96),   # Bank 0 col=9,row=0: A=97, B=96 — avoids I2C (83-86) and clk (88)
    1: (75, 74),   # Bank 1 col=21,row=2: A=75, B=74
    2: (29, 30),   # Bank 2 col=5,row=12: A=29, B=30 — not in BANK_PINS[2] output pool
}

# ---------------------------------------------------------------------------
# Target dataclass
# ---------------------------------------------------------------------------

@dataclass
class Target:
    name:       str
    verilog:    str           # full text of fuzz.v
    lpf_extra:  str = ""      # text appended after auto-generated pin constraints
    bank:       int = 0       # which bank's pins to use for IO
    # List of (portname, pin, direction, io_type) — if None, derive from verilog ports
    lpf_pins:   Optional[list] = None
    # If True, target lives under targets/highlevel/
    highlevel:  bool = False
    # Override the subdirectory name (relative to targets/)
    subdir:     Optional[str] = None

    def dir_path(self, base: Path) -> Path:
        if self.subdir:
            return base / self.subdir
        if self.highlevel:
            return base / "highlevel" / self.name
        return base / self.name


# ---------------------------------------------------------------------------
# Helpers for LPF / LDF / TCL generation
# ---------------------------------------------------------------------------

def make_lpf(target: Target) -> str:
    lines = ["BLOCK RESETPATHS;", "BLOCK ASYNCPATHS;", ""]
    if target.lpf_pins:
        for portname, pin, direction, io_type in target.lpf_pins:
            lines.append(f'LOCATE COMP "{portname}" SITE "{pin}";')
            lines.append(f'IOBUF PORT "{portname}" IO_TYPE={io_type};')
            lines.append("")
    # Add frequency constraint for clk if any pin is named clk
    if target.lpf_pins:
        clk_pins = [p for p in target.lpf_pins if p[0] == "clk"]
        if clk_pins:
            lines.append('FREQUENCY PORT "clk" 100.000000 MHz;')
    if target.lpf_extra:
        lines.append("")
        lines.append(target.lpf_extra.strip())
    lines.append("")
    return "\n".join(lines)


LDF_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<BaliProject version="3.2" title="fuzz" device="LCMXO2-1200HC-5TG100C" default_implementation="impl1">
    <Options/>
    <Implementation title="impl1" dir="impl1" description="impl1" synthesis="lse" default_strategy="Strategy1">
        <Options/>
        <Source name="fuzz.v" type="Verilog" type_short="Verilog"><Options/></Source>
        <Source name="fuzz.lpf" type="Logic Preference" type_short="LPF"><Options/></Source>
    </Implementation>
    <Strategy name="Strategy1" file="{sty}"/>
</BaliProject>
"""

TCL_TEMPLATE = """\
prj_project open "[file normalize [file join [file dirname [info script]] fuzz.ldf]]"
prj_run PAR    -impl impl1
prj_run Export -impl impl1 -task Bitgen
prj_project close
"""


def make_ldf() -> str:
    return LDF_TEMPLATE.format(sty=STY_REL)


# ---------------------------------------------------------------------------
# Pin pool helpers
# ---------------------------------------------------------------------------

def bank_pins(bank: int, n: int, start: int = 0) -> list[int]:
    """Return n pins from bank pool starting at offset start."""
    pool = BANK_PINS[bank]
    pins = pool[start:start + n]
    if len(pins) < n:
        raise ValueError(f"Not enough pins in bank {bank}: need {n}, have {len(pool) - start}")
    return pins


def clk_pin(bank: int) -> int:
    return BANK_PINS[bank][0]


def data_pin(bank: int, offset: int = 1) -> int:
    return BANK_PINS[bank][offset]


def out_pins(bank: int, n: int) -> list[int]:
    """Return n output pins from bank (starting after clk+3 data slots = index 4)."""
    return bank_pins(bank, n, start=4)


def lpf_pin_entry(name: str, pin: int, direction: str = "in", io_type: str = "LVCMOS33"):
    return (name, pin, direction, io_type)


# ---------------------------------------------------------------------------
# Convenience Verilog wrappers
# ---------------------------------------------------------------------------

def verilog_module(ports_decl: str, body: str, module_name: str = "fuzz") -> str:
    """Wrap body in a module declaration."""
    return f"module {module_name} (\n{ports_decl}\n);\n\n{textwrap.dedent(body)}\nendmodule\n"


# ---------------------------------------------------------------------------
# Per-category target builders
# ---------------------------------------------------------------------------

def build_ddr_iologic_targets() -> list[Target]:
    """DDR IOLOGIC primitives.

    IOLOGIC site type constraints on LCMXO2-1200HC TQFP100:
      Bank 0 = row 0 (top)    → TIOLOGIC  — ODDRX (TSIOLOGIC mode) works here
      Bank 1 = col 21 (right) → RIOLOGIC  — neither IDDRX nor ODDRX work here
      Bank 2 = row 12 (bottom)→ BSIOLOGIC — IDDRX (BSIOLOGIC mode) works here

    IDDRXE (simple single-ended DDR, not typed) works at all banks.
    ODDRXE (simple) works at bank 0 (TIOLOGIC).
    """
    targets = []

    # ---------------------------------------------------------------
    # IDDRXE — simple single-ended DDR input; works at all 3 banks
    # ---------------------------------------------------------------
    for bank in [0, 1, 2]:
        ck  = clk_pin(bank)
        d0  = data_pin(bank, 1)
        d1  = data_pin(bank, 2)
        ops = out_pins(bank, 4)
        vlog = """\
    wire gnd = 1'b0;
    wire q0a, q1a, q0b, q1b;
    IDDRXE u0 (.D(d0), .SCLK(clk), .RST(gnd), .Q0(q0a), .Q1(q1a));
    IDDRXE u1 (.D(d1), .SCLK(clk), .RST(gnd), .Q0(q0b), .Q1(q1b));
    reg [3:0] q;
    always @(posedge clk) q <= {q1b, q0b, q1a, q0a};
    assign {out3, out2, out1, out0} = q;
"""
        ports_decl = "    input wire clk, input wire d0, input wire d1,\n    output wire out0, out1, out2, out3"
        pin_list = [
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("d0",   d0),
            lpf_pin_entry("d1",   d1),
            lpf_pin_entry("out0", ops[0], "out"),
            lpf_pin_entry("out1", ops[1], "out"),
            lpf_pin_entry("out2", ops[2], "out"),
            lpf_pin_entry("out3", ops[3], "out"),
        ]
        targets.append(Target(
            name=f"iddrxe_bank{bank}",
            verilog=verilog_module(ports_decl, vlog),
            bank=bank,
            lpf_pins=pin_list,
        ))

    # ---------------------------------------------------------------
    # IDDRX2E / IDDRX4B / IDDRX71A — BSIOLOGIC only = bank 2 (bottom row)
    # These IDDR modes require BSIOLOGIC IO sites. On TQFP100:
    #   Bank 0 (row 0) = TIOLOGIC → FAILS
    #   Bank 1 (col 21) = RIOLOGIC → FAILS
    #   Bank 2 (row 12) = BSIOLOGIC → WORKS
    # D must also be on an A-side pad (A/B pair); use LVDS_PAIRS[2][0] = pin 42.
    # IDDRDQSX1A — SKIPPED (DQS group placement required)
    # ---------------------------------------------------------------
    bank = 2
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 8)
    lvds_pp = LVDS_PAIRS[bank][0]   # A-side of bank-2 diff pair (pin 42)

    vlog = f"""\
    wire gnd = 1'b0;
    wire eclk_w, sclk_w;
    wire q0, q1, q2, q3;
    ECLKSYNCA u_eclk (.ECLKI(clk), .STOP(gnd), .ECLKO(eclk_w));
    CLKDIVC #(.DIV("2.0"), .GSR("ENABLED")) u_div (.CLKI(eclk_w), .RST(gnd), .CDIV1(), .CDIVX(sclk_w));
    IDDRX2E u0 (.D(d0), .ECLK(eclk_w), .SCLK(sclk_w), .RST(gnd), .ALIGNWD(gnd), .Q0(q0), .Q1(q1), .Q2(q2), .Q3(q3));
    reg [3:0] q;
    always @(posedge sclk_w) q <= {{q3, q2, q1, q0}};
    assign {{out3, out2, out1, out0}} = q;
"""
    pin_list = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("d0",   lvds_pp),
        lpf_pin_entry("out0", ops[0], "out"),
        lpf_pin_entry("out1", ops[1], "out"),
        lpf_pin_entry("out2", ops[2], "out"),
        lpf_pin_entry("out3", ops[3], "out"),
    ]
    targets.append(Target(
        name=f"iddrx2e_bank{bank}",
        verilog=verilog_module("    input wire clk, input wire d0,\n    output wire out0, out1, out2, out3", vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    vlog = f"""\
    wire gnd = 1'b0;
    wire eclk_w, sclk_w;
    wire q0, q1, q2, q3, q4, q5, q6, q7;
    ECLKSYNCA u_eclk (.ECLKI(clk), .STOP(gnd), .ECLKO(eclk_w));
    CLKDIVC #(.DIV("4.0"), .GSR("ENABLED")) u_div (.CLKI(eclk_w), .RST(gnd), .CDIV1(), .CDIVX(sclk_w));
    IDDRX4B u0 (.D(d0), .ECLK(eclk_w), .SCLK(sclk_w), .RST(gnd), .ALIGNWD(gnd),
        .Q0(q0), .Q1(q1), .Q2(q2), .Q3(q3), .Q4(q4), .Q5(q5), .Q6(q6), .Q7(q7));
    reg [7:0] q;
    always @(posedge sclk_w) q <= {{q7, q6, q5, q4, q3, q2, q1, q0}};
    assign {{out7, out6, out5, out4, out3, out2, out1, out0}} = q;
"""
    pin_list = [lpf_pin_entry("clk", ck), lpf_pin_entry("d0", lvds_pp)] + [
        lpf_pin_entry(f"out{i}", ops[i], "out") for i in range(8)
    ]
    targets.append(Target(
        name=f"iddrx4b_bank{bank}",
        verilog=verilog_module("    input wire clk, input wire d0,\n    output wire out0, out1, out2, out3, out4, out5, out6, out7", vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    vlog = f"""\
    wire gnd = 1'b0;
    wire eclk_w, sclk_w;
    wire q0, q1, q2, q3, q4, q5, q6;
    ECLKSYNCA u_eclk (.ECLKI(clk), .STOP(gnd), .ECLKO(eclk_w));
    CLKDIVC #(.DIV("4.0"), .GSR("ENABLED")) u_div (.CLKI(eclk_w), .RST(gnd), .CDIV1(), .CDIVX(sclk_w));
    IDDRX71A u0 (.D(d0), .ECLK(eclk_w), .SCLK(sclk_w), .RST(gnd), .ALIGNWD(gnd),
        .Q0(q0), .Q1(q1), .Q2(q2), .Q3(q3), .Q4(q4), .Q5(q5), .Q6(q6));
    reg [6:0] q;
    always @(posedge sclk_w) q <= {{q6, q5, q4, q3, q2, q1, q0}};
    assign {{out6, out5, out4, out3, out2, out1, out0}} = q;
"""
    pin_list = [lpf_pin_entry("clk", ck), lpf_pin_entry("d0", lvds_pp)] + [
        lpf_pin_entry(f"out{i}", ops[i], "out") for i in range(7)
    ]
    targets.append(Target(
        name=f"iddrx71a_bank{bank}",
        verilog=verilog_module("    input wire clk, input wire d0,\n    output wire out0, out1, out2, out3, out4, out5, out6", vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    # ---------------------------------------------------------------
    # ODDRXE — simple single-ended DDR output; works at bank 0 (TIOLOGIC)
    # Also verified at bank 1/2 previously — restricting to bank 0 only for safety.
    # ---------------------------------------------------------------
    bank = 0
    ck   = clk_pin(bank)
    d0   = data_pin(bank, 1)
    d1   = data_pin(bank, 2)
    ops  = out_pins(bank, 1)
    lvds_pp = LVDS_PAIRS[bank][0]   # A-side of bank-0 diff pair (pin 97)

    vlog = f"""\
    wire gnd = 1'b0;
    wire qw;
    ODDRXE u0 (.D0(d0), .D1(d1), .SCLK(clk), .RST(gnd), .Q(qw));
    assign out0 = qw;
"""
    targets.append(Target(
        name="oddrxe_bank0",
        verilog=verilog_module("    input wire clk, input wire d0, input wire d1,\n    output wire out0", vlog),
        bank=bank,
        lpf_pins=[
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("d0",   d0),
            lpf_pin_entry("d1",   d1),
            lpf_pin_entry("out0", lvds_pp, "out"),
        ],
    ))

    # ---------------------------------------------------------------
    # ODDRX2E / ODDRX4B / ODDRX71A — TSIOLOGIC only = bank 0 (top row)
    # These ODDR modes require TSIOLOGIC IO sites. On TQFP100:
    #   Bank 0 (row 0) = TIOLOGIC → WORKS (PAR accepts TSIOLOGIC at TIOLOGIC site)
    #   Bank 1 (col 21) = RIOLOGIC → FAILS
    #   Bank 2 (row 12) = BSIOLOGIC → NOT tested here
    # Q output must be on A-side pad; use LVDS_PAIRS[0][0] = pin 97.
    # ODDRDQSX1A / TDDRA — SKIPPED (DQS group placement required)
    # ---------------------------------------------------------------
    bank = 0
    ck   = clk_pin(bank)
    d0   = data_pin(bank, 1)
    d1   = data_pin(bank, 2)
    ops  = out_pins(bank, 1)
    lvds_pp = LVDS_PAIRS[bank][0]   # pin 97

    vlog = f"""\
    wire gnd = 1'b0;
    wire eclk_w, sclk_w, qw;
    ECLKSYNCA u_eclk (.ECLKI(clk), .STOP(gnd), .ECLKO(eclk_w));
    CLKDIVC #(.DIV("2.0"), .GSR("ENABLED")) u_div (.CLKI(eclk_w), .RST(gnd), .CDIV1(), .CDIVX(sclk_w));
    ODDRX2E u0 (.D0(d0), .D1(d1), .D2(d0), .D3(d1), .ECLK(eclk_w), .SCLK(sclk_w), .RST(gnd), .Q(qw));
    assign out0 = qw;
"""
    targets.append(Target(
        name="oddrx2e_bank0",
        verilog=verilog_module("    input wire clk, input wire d0, input wire d1,\n    output wire out0", vlog),
        bank=bank,
        lpf_pins=[
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("d0",   d0),
            lpf_pin_entry("d1",   d1),
            lpf_pin_entry("out0", lvds_pp, "out"),
        ],
    ))

    vlog = f"""\
    wire gnd = 1'b0;
    wire eclk_w, sclk_w, qw;
    ECLKSYNCA u_eclk (.ECLKI(clk), .STOP(gnd), .ECLKO(eclk_w));
    CLKDIVC #(.DIV("4.0"), .GSR("ENABLED")) u_div (.CLKI(eclk_w), .RST(gnd), .CDIV1(), .CDIVX(sclk_w));
    ODDRX4B u0 (.D0(d0), .D1(d1), .D2(d0), .D3(d1), .D4(d0), .D5(d1), .D6(d0), .D7(d1),
        .ECLK(eclk_w), .SCLK(sclk_w), .RST(gnd), .Q(qw));
    assign out0 = qw;
"""
    targets.append(Target(
        name="oddrx4b_bank0",
        verilog=verilog_module("    input wire clk, input wire d0, input wire d1,\n    output wire out0", vlog),
        bank=bank,
        lpf_pins=[
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("d0",   d0),
            lpf_pin_entry("d1",   d1),
            lpf_pin_entry("out0", lvds_pp, "out"),
        ],
    ))

    vlog = f"""\
    wire gnd = 1'b0;
    wire eclk_w, sclk_w, qw;
    ECLKSYNCA u_eclk (.ECLKI(clk), .STOP(gnd), .ECLKO(eclk_w));
    CLKDIVC #(.DIV("4.0"), .GSR("ENABLED")) u_div (.CLKI(eclk_w), .RST(gnd), .CDIV1(), .CDIVX(sclk_w));
    ODDRX71A u0 (.ECLK(eclk_w), .SCLK(sclk_w), .D0(d0), .D1(d1), .D2(d0), .D3(d1), .D4(d0), .D5(d1), .D6(d0), .RST(gnd), .Q(qw));
    assign out0 = qw;
"""
    targets.append(Target(
        name="oddrx71a_bank0",
        verilog=verilog_module("    input wire clk, input wire d0, input wire d1,\n    output wire out0", vlog),
        bank=bank,
        lpf_pins=[
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("d0",   d0),
            lpf_pin_entry("d1",   d1),
            lpf_pin_entry("out0", lvds_pp, "out"),
        ],
    ))

    return targets


def build_io_ff_targets() -> list[Target]:
    """IO flip-flop primitives — bank 0 and bank 1 only."""
    targets = []

    # IFS = input flip-flops; OFS = output flip-flops
    # Suffix key: B=async-preset, D=async-clear, I=sync-clear, J=sync-preset
    # P variants have SP (clock enable), S variants don't
    p_variants = [
        ("ifs1p3bx", "IFS1P3BX", "D,SP,SCLK,PD", "Q", True),
        ("ifs1p3dx", "IFS1P3DX", "D,SP,SCLK,CD", "Q", True),
        ("ifs1p3ix", "IFS1P3IX", "D,SP,SCLK,CD", "Q", True),
        ("ifs1p3jx", "IFS1P3JX", "D,SP,SCLK,PD", "Q", True),
        ("ifs1s1b",  "IFS1S1B",  "D,SCLK,PD",    "Q", False),
        ("ifs1s1d",  "IFS1S1D",  "D,SCLK,CD",    "Q", False),
        ("ifs1s1i",  "IFS1S1I",  "D,SCLK,CD",    "Q", False),
        ("ifs1s1j",  "IFS1S1J",  "D,SCLK,PD",    "Q", False),
        ("ofs1p3bx", "OFS1P3BX", "D,SP,SCLK,PD", "Q", True),
        ("ofs1p3dx", "OFS1P3DX", "D,SP,SCLK,CD", "Q", True),
        ("ofs1p3ix", "OFS1P3IX", "D,SP,SCLK,CD", "Q", True),
        ("ofs1p3jx", "OFS1P3JX", "D,SP,SCLK,PD", "Q", True),
    ]

    for bank in [0, 1]:
        ck  = clk_pin(bank)
        d0  = data_pin(bank, 1)
        ops = out_pins(bank, 4)

        for short_name, prim, port_str, out_port, has_sp in p_variants:
            # Build port connections
            # All control signals except D and SCLK tied to gnd
            ports = port_str.split(",")
            conn_lines = []
            is_output_ff = short_name.startswith("ofs")
            for p in ports:
                if p == "D":
                    if is_output_ff:
                        # OFS1P: D from fabric reg (data comes from registered input)
                        conn_lines.append(f"        .D(d_fabric)")
                    else:
                        conn_lines.append(f"        .D(d0)")
                elif p == "SCLK":
                    conn_lines.append(f"        .SCLK(clk)")
                elif p in ("SP", "PD", "CD"):
                    conn_lines.append(f"        .{p}(gnd)")
                else:
                    conn_lines.append(f"        .{p}(gnd)")
            # output
            conn_lines.append(f"        .{out_port}(out0)")

            conn_str = ",\n".join(conn_lines)
            if is_output_ff:
                # OFS1P: Q must drive output pad directly (output IOLOGIC FF).
                # Feed D from a fabric FF driven by the input pad.
                vlog = f"""\
    wire gnd = 1'b0;
    reg d_fabric;
    always @(posedge clk) d_fabric <= d0;
    {prim} u0 (
{conn_str}
    );
"""
            else:
                # IFS1P: Q is from input IOLOGIC FF → fabric reg → output pad
                vlog = f"""\
    wire gnd = 1'b0;
    wire qw;
    {prim} u0 (
{conn_str.replace('(out0)', '(qw)')}
    );
    reg out0_r;
    always @(posedge clk) out0_r <= qw;
    assign out0 = out0_r;
"""
            ports_decl = "    input wire clk, input wire d0,\n    output wire out0"
            pin_list = [
                lpf_pin_entry("clk",  ck),
                lpf_pin_entry("d0",   d0),
                lpf_pin_entry("out0", ops[0], "out"),
            ]
            targets.append(Target(
                name=f"{short_name}_bank{bank}",
                verilog=verilog_module(ports_decl, vlog),
                bank=bank,
                lpf_pins=pin_list,
            ))

    return targets


def build_delay_targets() -> list[Target]:
    """Delay and DQS buffer primitives."""
    targets = []

    for bank in [0, 1]:
        ck  = clk_pin(bank)
        d0  = data_pin(bank, 1)
        ops = out_pins(bank, 4)

        # ---------------------------------------------------------------
        # DELAYE / DELAYD — SKIPPED
        # Diamond MAP rule: delay cell output can only drive another IO cell
        # (IOLOGIC or pad), never a fabric FF or BB bidir buffer.
        # The only valid topology is: input_pad → DELAY → IOLOGIC → output_pad.
        # That requires a paired IDDRXE/ODDRXE which conflates two primitives.
        # Fuzz these as part of the IDDRXE targets (where the delay is in path).
        # Standalone delay targets are not fuzzable on this device.
        # ---------------------------------------------------------------
        # (targets not appended)

        # ---------------------------------------------------------------
        # DQSBUFH / DQSDLLC / DLLDELC / IDDRDQSX1A / ODDRDQSX1A / TDDRA — SKIPPED
        # All DQS primitives require placement in a DQS IO group — a hardware
        # grouping of adjacent IO pads with DQS-capable routing. Diamond PAR
        # enforces this at BlockCheck time:
        #   "DQSDLLC: Unable to find group. Component not placed."
        #   "MIDDR_MODDR comp is used as DQS pin, DQSW90MUX must select CLKOMUX."
        # These primitives cannot be fuzzed standalone with arbitrary LPF pin
        # assignments. They require a full DDR memory bus topology with DQS strobe
        # pins wired to the correct DQS IO group in the physical PCB routing.
        # Our TQFP100 Hantek board does not expose accessible DQS IO groups.
        # These primitives are documented by prjtrellis — skipping fuzz here.
        # ---------------------------------------------------------------
        # (targets not appended)

    return targets


def build_io_buffer_targets() -> list[Target]:
    """Single-ended and differential IO buffer primitives — bank 0."""
    targets = []

    bank = 0
    ck  = clk_pin(bank)
    ops = out_pins(bank, 8)
    d0  = data_pin(bank, 1)
    d1  = data_pin(bank, 2)
    pp, pn = LVDS_PAIRS[bank]   # diff pair pins

    # ---------------------------------------------------------------
    # Bidirectional buffers: BB, BBPD, BBPU, BBW
    # Require inout port (B) and separate I (drive), T (tristate), O (receive)
    # ---------------------------------------------------------------
    for prim in ["BB", "BBPD", "BBPU", "BBW"]:
        vlog = f"""\
    wire gnd = 1'b0;
    wire rx;
    {prim} u0 (.I(d0), .T(gnd), .O(rx), .B(bidir));
    reg out0_r;
    always @(posedge clk) out0_r <= rx;
    assign out0 = out0_r;
"""
        ports_decl = "    input wire clk, input wire d0, inout wire bidir,\n    output wire out0"
        pin_list = [
            lpf_pin_entry("clk",   ck),
            lpf_pin_entry("d0",    d0),
            lpf_pin_entry("bidir", ops[0]),
            lpf_pin_entry("out0",  ops[1], "out"),
        ]
        targets.append(Target(
            name=f"{prim.lower()}_bank{bank}",
            verilog=verilog_module(ports_decl, vlog),
            bank=bank,
            lpf_pins=pin_list,
        ))

    # ---------------------------------------------------------------
    # Input buffers: IB, IBPD, IBPU
    # ---------------------------------------------------------------
    for prim in ["IB", "IBPD", "IBPU"]:
        vlog = f"""\
    wire rx;
    {prim} u0 (.I(pad_in), .O(rx));
    reg out0_r;
    always @(posedge clk) out0_r <= rx;
    assign out0 = out0_r;
"""
        ports_decl = "    input wire clk, input wire pad_in,\n    output wire out0"
        pin_list = [
            lpf_pin_entry("clk",    ck),
            lpf_pin_entry("pad_in", d0),
            lpf_pin_entry("out0",   ops[0], "out"),
        ]
        targets.append(Target(
            name=f"{prim.lower()}_bank{bank}",
            verilog=verilog_module(ports_decl, vlog),
            bank=bank,
            lpf_pins=pin_list,
        ))

    # ---------------------------------------------------------------
    # Output buffers: OB
    # ---------------------------------------------------------------
    vlog = f"""\
    OB u0 (.I(d0), .O(pad_out));
"""
    ports_decl = "    input wire clk, input wire d0,\n    output wire pad_out"
    pin_list = [
        lpf_pin_entry("clk",     ck),
        lpf_pin_entry("d0",      d0),
        lpf_pin_entry("pad_out", ops[0], "out"),
    ]
    targets.append(Target(
        name=f"ob_bank{bank}",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    # ---------------------------------------------------------------
    # OBZ — output with tristate
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    OBZ u0 (.I(d0), .T(gnd), .O(pad_out));
"""
    ports_decl = "    input wire clk, input wire d0,\n    output wire pad_out"
    pin_list = [
        lpf_pin_entry("clk",     ck),
        lpf_pin_entry("d0",      d0),
        lpf_pin_entry("pad_out", ops[0], "out"),
    ]
    targets.append(Target(
        name=f"obz_bank{bank}",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    # ---------------------------------------------------------------
    # OBZPU — output with tristate and pull-up
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    OBZPU u0 (.I(d0), .T(gnd), .O(pad_out));
"""
    ports_decl = "    input wire clk, input wire d0,\n    output wire pad_out"
    pin_list = [
        lpf_pin_entry("clk",     ck),
        lpf_pin_entry("d0",      d0),
        lpf_pin_entry("pad_out", ops[0], "out"),
    ]
    targets.append(Target(
        name=f"obzpu_bank{bank}",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    # ---------------------------------------------------------------
    # OBCO — complementary output (OT and OC)
    # ---------------------------------------------------------------
    vlog = f"""\
    OBCO u0 (.I(d0), .OT(pad_ot), .OC(pad_oc));
"""
    ports_decl = "    input wire clk, input wire d0,\n    output wire pad_ot, pad_oc"
    pin_list = [
        lpf_pin_entry("clk",    ck),
        lpf_pin_entry("d0",     d0),
        lpf_pin_entry("pad_ot", ops[0], "out"),
        lpf_pin_entry("pad_oc", ops[1], "out"),
    ]
    targets.append(Target(
        name=f"obco_bank{bank}",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    # ---------------------------------------------------------------
    # ILVDS — LVDS input (differential pair)
    # ---------------------------------------------------------------
    vlog = f"""\
    wire rx;
    ILVDS u0 (.A(pad_p), .AN(pad_n), .Z(rx));
    reg out0_r;
    always @(posedge clk) out0_r <= rx;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk, input wire pad_p, input wire pad_n,\n    output wire out0"
    pin_list = [
        lpf_pin_entry("clk",  ck,         "in",  "LVCMOS33"),
        lpf_pin_entry("pad_p", pp,        "in",  "LVDS25"),
        lpf_pin_entry("pad_n", pn,        "in",  "LVDS25"),
        lpf_pin_entry("out0",  ops[0],    "out", "LVCMOS33"),
    ]
    targets.append(Target(
        name=f"ilvds_bank{bank}",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    # ---------------------------------------------------------------
    # OLVDS — SKIPPED
    # Differential output (LVDS25) requires A/B pad pairs. Our TQFP100 board
    # wired used pins don't include a confirmed A/B pair. OLVDS is documented
    # by prjtrellis. Skip to avoid PAR placement failure.
    # ERROR: par: ChipCheck: LVDS comp pad_p is placed on site PT12C.
    #        Only the A/B pad pair supports true differential output buffers.
    # (target not appended)
    # ---------------------------------------------------------------

    # ---------------------------------------------------------------
    # LVDSOB — LVDS output buffer (D + enable)
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    LVDSOB u0 (.D(d0), .E(gnd), .Q(pad_out));
"""
    ports_decl = "    input wire clk, input wire d0,\n    output wire pad_out"
    pin_list = [
        lpf_pin_entry("clk",     ck),
        lpf_pin_entry("d0",      d0),
        lpf_pin_entry("pad_out", ops[0], "out"),
    ]
    targets.append(Target(
        name=f"lvdsob_bank{bank}",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    # ---------------------------------------------------------------
    # INRDB — input with read-back (D + E)
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire rx;
    INRDB u0 (.D(pad_in), .E(gnd), .Q(rx));
    reg out0_r;
    always @(posedge clk) out0_r <= rx;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk, input wire pad_in,\n    output wire out0"
    pin_list = [
        lpf_pin_entry("clk",    ck),
        lpf_pin_entry("pad_in", d0),
        lpf_pin_entry("out0",   ops[0], "out"),
    ]
    targets.append(Target(
        name=f"inrdb_bank{bank}",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    # ---------------------------------------------------------------
    # BCINRD — bank-level control (no pad)
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    BCINRD #(.BANKID(0)) u0 (.INRDENI(gnd));
    reg out0_r;
    always @(posedge clk) out0_r <= gnd;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    pin_list = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("out0", ops[0], "out"),
    ]
    targets.append(Target(
        name=f"bcinrd_bank{bank}",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    # ---------------------------------------------------------------
    # BCLVDSO — bank-level LVDS output enable
    # LVDSENI must be driven by an IO pad signal, not a constant.
    # ---------------------------------------------------------------
    bclvdso_d0 = data_pin(bank, 1)
    vlog = f"""\
    wire gnd = 1'b0;
    BCLVDSO u0 (.LVDSENI(lvds_en));
    reg out0_r;
    always @(posedge clk) out0_r <= lvds_en;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk, input wire lvds_en,\n    output wire out0"
    pin_list = [
        lpf_pin_entry("clk",      ck),
        lpf_pin_entry("lvds_en",  bclvdso_d0),
        lpf_pin_entry("out0",     ops[0], "out"),
    ]
    targets.append(Target(
        name=f"bclvdso_bank{bank}",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=pin_list,
    ))

    return targets


def build_clock_targets() -> list[Target]:
    """Clock routing primitives."""
    targets = []

    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 4)

    internal_pin_list = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("out0", ops[0], "out"),
    ]

    # ---------------------------------------------------------------
    # ECLKSYNCA — ECLK synchroniser
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire eclko_w;
    ECLKSYNCA u0 (.ECLKI(clk), .STOP(gnd), .ECLKO(eclko_w));
    reg out0_r;
    always @(posedge eclko_w) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="eclksynca",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # ---------------------------------------------------------------
    # ECLKBRIDGECS — ECLK bridge with clock select
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire ecsout_w;
    ECLKBRIDGECS u0 (.CLK0(clk), .CLK1(clk), .SEL(gnd), .ECSOUT(ecsout_w));
    reg out0_r;
    always @(posedge ecsout_w) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="eclkbridgecs",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # ---------------------------------------------------------------
    # CLKDIVC — clock divider
    # ---------------------------------------------------------------
    for div in [2, 4]:  # valid DIV values: 2 and 4 only — 7 and 8 are invalid for CLKDIVC
        vlog = f"""\
    wire gnd = 1'b0;
    wire cdiv1_w, cdivx_w;
    CLKDIVC #(.DIV("{div}.0"), .GSR("ENABLED")) u0 (.RST(gnd), .CLKI(clk), .ALIGNWD(gnd), .CDIV1(cdiv1_w), .CDIVX(cdivx_w));
    reg out0_r;
    always @(posedge cdivx_w) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
        ports_decl = "    input wire clk,\n    output wire out0"
        targets.append(Target(
            name=f"clkdivc_div{div}",
            verilog=verilog_module(ports_decl, vlog),
            bank=bank,
            lpf_pins=internal_pin_list,
        ))

    # ---------------------------------------------------------------
    # CLKFBBUFA — global clock feedback buffer
    # Input must be from a PLL CLKOP output — cannot drive from pad directly.
    # Use minimal EHXPLLJ with CLKFBBUFA on feedback path.
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire vcc = 1'b1;
    wire pll_clkop, pll_lock, fb_w;
    // CLKFBBUFA: output Z can only connect to EHXPLLJ.CLKFB — no other routing.
    // Wire: CLKOP → CLKFBBUFA.A → Z → CLKFB (normal external feedback loop).
    // Use FEEDBK_PATH="USERCLOCK" so the PLL accepts an external feedback path.
    EHXPLLJ #(
        .CLKOP_DIV(1), .CLKFB_DIV(1), .CLKI_DIV(1),
        .FEEDBK_PATH("USERCLOCK"),
        .CLKOP_ENABLE("ENABLED"),
        .STDBY_ENABLE("DISABLED"),
        .PLL_LOCK_MODE(0)
    ) u_pll (
        .CLKI(clk), .CLKFB(fb_w),
        .RST(gnd), .STDBY(gnd), .RESETM(gnd), .RESETC(gnd), .RESETD(gnd),
        .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd),
        .PHASESTEP(gnd), .LOADREG(gnd),
        .PLLWAKESYNC(gnd), .ENCLKOP(vcc), .ENCLKOS(gnd), .ENCLKOS2(gnd), .ENCLKOS3(gnd),
        .CLKOP(pll_clkop), .LOCK(pll_lock)
    );
    CLKFBBUFA u0 (.A(pll_clkop), .Z(fb_w));
    reg out0_r;
    always @(posedge pll_clkop) out0_r <= pll_lock;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="clkfbbufa",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # ---------------------------------------------------------------
    # DCCA — dynamic clock control (gating)
    # ---------------------------------------------------------------
    vlog = f"""\
    wire vcc = 1'b1;
    wire clko_w;
    DCCA u0 (.CLKI(clk), .CE(vcc), .CLKO(clko_w));
    reg out0_r;
    always @(posedge clko_w) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="dcca",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # ---------------------------------------------------------------
    # DCMA — dynamic clock mux
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire dcmout_w;
    DCMA u0 (.CLK0(clk), .CLK1(clk), .SEL(gnd), .DCMOUT(dcmout_w));
    reg out0_r;
    always @(posedge dcmout_w) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="dcma",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # ---------------------------------------------------------------
    # PLLREFCS — PLL reference clock select
    # Output must drive CLKI of a single PLL instance (Diamond constraint).
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0, vcc = 1'b1;
    wire pllref_out, pll_clkop, pll_lock;
    PLLREFCS u_ref (.CLK0(clk), .CLK1(gnd), .SEL(gnd), .PLLCSOUT(pllref_out));
    EHXPLLJ #(
        .CLKOP_DIV(1), .CLKFB_DIV(1), .CLKI_DIV(1),
        .FEEDBK_PATH("CLKOP"),
        .CLKOP_ENABLE("ENABLED"),
        .STDBY_ENABLE("DISABLED"),
        .PLL_LOCK_MODE(0)
    ) u_pll (
        .CLKI(pllref_out), .CLKFB(pll_clkop),
        .RST(gnd), .STDBY(gnd), .RESETM(gnd), .RESETC(gnd), .RESETD(gnd),
        .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd),
        .PHASESTEP(gnd), .LOADREG(gnd),
        .PLLWAKESYNC(gnd), .ENCLKOP(vcc), .ENCLKOS(gnd), .ENCLKOS2(gnd), .ENCLKOS3(gnd),
        .CLKOP(pll_clkop), .LOCK(pll_lock)
    );
    reg out0_r;
    always @(posedge clk) out0_r <= pll_lock;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="pllrefcs",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    return targets


def build_pll_targets() -> list[Target]:
    """EHXPLLJ in various configurations."""
    targets = []

    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 4)
    internal_pin_list = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("out0", ops[0], "out"),
    ]

    def pll_body(extra_params: str = "", extra_enables: str = "", extra_outputs: str = "",
                 extra_output_regs: str = ""):
        return f"""\
    wire gnd = 1'b0;
    wire vcc = 1'b1;
    wire clkop_w, lock_w, intlock_w, refclk_w, clkintfb_w;
    wire clkos_w, clkos2_w, clkos3_w;
    EHXPLLJ #(
        .CLKI_DIV(1),
        .CLKFB_DIV(1),
        .CLKOP_DIV(1),
        .CLKOP_ENABLE("ENABLED"),
        .FEEDBK_PATH("CLKOP"){extra_params}
    ) u0 (
        .CLKI(clk),
        .CLKFB(clkop_w),
        .RST(gnd),
        .STDBY(gnd),
        .PLLWAKESYNC(gnd),
        .PHASESEL1(gnd),
        .PHASESEL0(gnd),
        .PHASEDIR(gnd),
        .PHASESTEP(gnd),
        .LOADREG(gnd),
        .RESETM(gnd),
        .RESETC(gnd),
        .RESETD(gnd),
        .ENCLKOP(vcc){extra_enables},
        .PLLCLK(gnd),
        .PLLRST(gnd),
        .PLLSTB(gnd),
        .PLLWE(gnd),
        .PLLADDR4(gnd), .PLLADDR3(gnd), .PLLADDR2(gnd), .PLLADDR1(gnd), .PLLADDR0(gnd),
        .PLLDATI7(gnd), .PLLDATI6(gnd), .PLLDATI5(gnd), .PLLDATI4(gnd),
        .PLLDATI3(gnd), .PLLDATI2(gnd), .PLLDATI1(gnd), .PLLDATI0(gnd),
        .CLKOP(clkop_w),
        .CLKOS(clkos_w),
        .CLKOS2(clkos2_w),
        .CLKOS3(clkos3_w),
        .LOCK(lock_w),
        .INTLOCK(intlock_w),
        .REFCLK(refclk_w),
        .CLKINTFB(clkintfb_w)
    );
    reg out0_r;
    always @(posedge clkop_w) out0_r <= lock_w{extra_output_regs};
    assign out0 = out0_r{extra_outputs};
"""

    _enclk_gnd = """,
        .ENCLKOS(gnd),
        .ENCLKOS2(gnd),
        .ENCLKOS3(gnd)"""

    # Basic PLL
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="ehxpllj_basic",
        verilog=verilog_module(ports_decl, pll_body(extra_enables=_enclk_gnd)),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # CLKFB_DIV=2
    targets.append(Target(
        name="ehxpllj_div2",
        verilog=verilog_module(ports_decl, pll_body(
            extra_params=",\n        .CLKFB_DIV(2)",
            extra_enables=_enclk_gnd,
        )),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # 4 outputs enabled
    extra_params_4out = """,
        .CLKOS_DIV(4),
        .CLKOS_ENABLE("ENABLED"),
        .CLKOS2_DIV(2),
        .CLKOS2_ENABLE("ENABLED"),
        .CLKOS3_DIV(16),
        .CLKOS3_ENABLE("ENABLED")"""
    extra_enables_4out = """,
        .ENCLKOS(vcc),
        .ENCLKOS2(vcc),
        .ENCLKOS3(vcc)"""
    extra_outputs_4out = " ^ clkos_w ^ clkos2_w ^ clkos3_w"
    targets.append(Target(
        name="ehxpllj_4out",
        verilog=verilog_module(ports_decl, pll_body(
            extra_params=extra_params_4out,
            extra_enables=extra_enables_4out,
            extra_output_regs=extra_outputs_4out,
        )),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    return targets


def build_osch_targets() -> list[Target]:
    """Internal oscillator at each supported frequency."""
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 2)
    freqs = ["2.08", "4.16", "8.31", "16.63", "26.00", "38.00", "48.00", "88.67", "133.00"]

    for freq in freqs:
        safe_name = freq.replace(".", "_")
        vlog = f"""\
    wire osc_w;
    wire gnd = 1'b0;
    OSCH #(.NOM_FREQ("{freq}")) u0 (.STDBY(gnd), .OSC(osc_w));
    reg out0_r;
    always @(posedge osc_w) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
        ports_decl = "    input wire clk,\n    output wire out0"
        pin_list = [
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("out0", ops[0], "out"),
        ]
        targets.append(Target(
            name=f"osch_freq_{safe_name}mhz",
            verilog=verilog_module(ports_decl, vlog),
            bank=bank,
            lpf_pins=pin_list,
        ))

    return targets


def build_ebr_targets() -> list[Target]:
    """Embedded block RAM primitives."""
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 2)

    internal_pin_list = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("out0", ops[0], "out"),
    ]

    # ---------------------------------------------------------------
    # DPR16X4C — 16x4 distributed RAM (not EBR)
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire [3:0] do_w;
    DPR16X4C u0 (
        .DI3(gnd), .DI2(gnd), .DI1(gnd), .DI0(gnd),
        .WAD3(gnd), .WAD2(gnd), .WAD1(gnd), .WAD0(gnd),
        .WRE(gnd), .WCK(clk),
        .RAD3(gnd), .RAD2(gnd), .RAD1(gnd), .RAD0(gnd),
        .DO3(do_w[3]), .DO2(do_w[2]), .DO1(do_w[1]), .DO0(do_w[0])
    );
    reg [3:0] q;
    always @(posedge clk) q <= do_w;
    assign out0 = ^q;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="dpr16x4c",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # ---------------------------------------------------------------
    # SPR16X4C — 16x4 single-port distributed RAM
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire [3:0] do_w;
    SPR16X4C u0 (
        .DI3(gnd), .DI2(gnd), .DI1(gnd), .DI0(gnd),
        .AD3(gnd), .AD2(gnd), .AD1(gnd), .AD0(gnd),
        .WRE(gnd), .CK(clk),
        .DO3(do_w[3]), .DO2(do_w[2]), .DO1(do_w[1]), .DO0(do_w[0])
    );
    reg [3:0] q;
    always @(posedge clk) q <= do_w;
    assign out0 = ^q;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="spr16x4c",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # ---------------------------------------------------------------
    # DP8KC — true dual-port EBR
    # Data widths: 1, 2, 4, 9 (and note 18 is not valid for DP8KC)
    # ---------------------------------------------------------------
    for width in [1, 2, 4, 9]:
        # data width → number of data bits (excl parity)
        dw = width if width < 9 else 8
        pw = 0 if width < 9 else 1
        addr_bits = {1: 13, 2: 12, 4: 11, 9: 10}[width]

        do_bits = dw + pw
        do_w_str = " | ".join(f"doa_w[{i}]" for i in range(do_bits)) if do_bits > 1 else "doa_w[0]"

        vlog = f"""\
    wire gnd = 1'b0;
    wire [{do_bits-1}:0] doa_w;
    DP8KC #(
        .DATA_WIDTH_A({width}),
        .DATA_WIDTH_B({width}),
        .REGMODE_A("NOREG"),
        .REGMODE_B("NOREG"),
        .WRITEMODE_A("NORMAL"),
        .WRITEMODE_B("NORMAL"),
        .INITVAL_00("0x00000000000000000000000000000000000000000000000000000000000000000000000000000000")
    ) u0 (
        .CLKA(clk), .CEA(gnd), .OCEA(gnd), .WEA(gnd), .CSA2(gnd), .CSA1(gnd), .CSA0(gnd), .RSTA(gnd),
        .ADA{addr_bits-1}(gnd), .ADA{addr_bits-2}(gnd), .ADA{addr_bits-3}(gnd), .ADA{addr_bits-4}(gnd),
        .ADA{addr_bits-5}(gnd), .ADA{addr_bits-6}(gnd), .ADA{addr_bits-7}(gnd), .ADA{addr_bits-8}(gnd),
        .ADA{addr_bits-9}(gnd), .ADA{addr_bits-10}(gnd),
        .DIA7(gnd), .DIA6(gnd), .DIA5(gnd), .DIA4(gnd),
        .DIA3(gnd), .DIA2(gnd), .DIA1(gnd), .DIA0(gnd),
        .DOA7(doa_w[7]), .DOA6(doa_w[6]), .DOA5(doa_w[5]), .DOA4(doa_w[4]),
        .DOA3(doa_w[3]), .DOA2(doa_w[2]), .DOA1(doa_w[1]), .DOA0(doa_w[0]),
        .CLKB(clk), .CEB(gnd), .OCEB(gnd), .WEB(gnd), .CSB2(gnd), .CSB1(gnd), .CSB0(gnd), .RSTB(gnd),
        .ADB{addr_bits-1}(gnd), .ADB{addr_bits-2}(gnd), .ADB{addr_bits-3}(gnd), .ADB{addr_bits-4}(gnd),
        .ADB{addr_bits-5}(gnd), .ADB{addr_bits-6}(gnd), .ADB{addr_bits-7}(gnd), .ADB{addr_bits-8}(gnd),
        .ADB{addr_bits-9}(gnd), .ADB{addr_bits-10}(gnd),
        .DIB7(gnd), .DIB6(gnd), .DIB5(gnd), .DIB4(gnd),
        .DIB3(gnd), .DIB2(gnd), .DIB1(gnd), .DIB0(gnd)
    );
    reg out0_r;
    always @(posedge clk) out0_r <= ^doa_w;
    assign out0 = out0_r;
"""
        ports_decl = "    input wire clk,\n    output wire out0"
        targets.append(Target(
            name=f"dp8kc_x{width}",
            verilog=verilog_module(ports_decl, vlog),
            bank=bank,
            lpf_pins=internal_pin_list,
        ))

    # ---------------------------------------------------------------
    # PDPW8KC — pseudo-dual-port with 18-bit write port
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire [17:0] do_w;
    PDPW8KC #(
        .DATA_WIDTH_W(18),
        .DATA_WIDTH_R(9),
        .INITVAL_00("0x00000000000000000000000000000000000000000000000000000000000000000000000000000000")
    ) u0 (
        .CLKW(clk), .CEW(gnd), .CSW2(gnd), .CSW1(gnd), .CSW0(gnd), .RST(gnd),
        .ADW8(gnd), .ADW7(gnd), .ADW6(gnd), .ADW5(gnd), .ADW4(gnd),
        .ADW3(gnd), .ADW2(gnd), .ADW1(gnd), .ADW0(gnd),
        .DI17(gnd), .DI16(gnd), .DI15(gnd), .DI14(gnd), .DI13(gnd),
        .DI12(gnd), .DI11(gnd), .DI10(gnd), .DI9(gnd),
        .DI8(gnd),  .DI7(gnd),  .DI6(gnd),  .DI5(gnd),
        .DI4(gnd),  .DI3(gnd),  .DI2(gnd),  .DI1(gnd),  .DI0(gnd),
        .CLKR(clk), .CER(gnd), .OCER(gnd), .CSR2(gnd), .CSR1(gnd), .CSR0(gnd),
        .ADR10(gnd), .ADR9(gnd), .ADR8(gnd), .ADR7(gnd), .ADR6(gnd),
        .ADR5(gnd),  .ADR4(gnd), .ADR3(gnd), .ADR2(gnd), .ADR1(gnd), .ADR0(gnd),
        .DO17(do_w[17]), .DO16(do_w[16]), .DO15(do_w[15]), .DO14(do_w[14]),
        .DO13(do_w[13]), .DO12(do_w[12]), .DO11(do_w[11]), .DO10(do_w[10]),
        .DO9(do_w[9]),   .DO8(do_w[8]),   .DO7(do_w[7]),   .DO6(do_w[6]),
        .DO5(do_w[5]),   .DO4(do_w[4]),   .DO3(do_w[3]),   .DO2(do_w[2]),
        .DO1(do_w[1]),   .DO0(do_w[0])
    );
    reg out0_r;
    always @(posedge clk) out0_r <= ^do_w;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="pdpw8kc_x18",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # ---------------------------------------------------------------
    # SP8KC — single-port EBR
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire [8:0] do_w;
    SP8KC #(
        .DATA_WIDTH(9),
        .REGMODE("NOREG"),
        .INITVAL_00("0x00000000000000000000000000000000000000000000000000000000000000000000000000000000")
    ) u0 (
        .CLK(clk), .CE(gnd), .OCE(gnd), .WE(gnd), .CS2(gnd), .CS1(gnd), .CS0(gnd), .RST(gnd),
        .AD10(gnd), .AD9(gnd), .AD8(gnd), .AD7(gnd), .AD6(gnd),
        .AD5(gnd),  .AD4(gnd), .AD3(gnd), .AD2(gnd), .AD1(gnd), .AD0(gnd),
        .DI8(gnd), .DI7(gnd), .DI6(gnd), .DI5(gnd), .DI4(gnd),
        .DI3(gnd), .DI2(gnd), .DI1(gnd), .DI0(gnd),
        .DO8(do_w[8]), .DO7(do_w[7]), .DO6(do_w[6]), .DO5(do_w[5]),
        .DO4(do_w[4]), .DO3(do_w[3]), .DO2(do_w[2]), .DO1(do_w[1]), .DO0(do_w[0])
    );
    reg out0_r;
    always @(posedge clk) out0_r <= ^do_w;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="sp8kc_x9",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    # ---------------------------------------------------------------
    # FIFO8KB — FIFO
    # ---------------------------------------------------------------
    vlog = f"""\
    wire gnd = 1'b0;
    wire [17:0] q_w;
    wire ef_w, aef_w, af_w, ff_w;
    FIFO8KB #(
        .DATA_WIDTH_W(18),
        .DATA_WIDTH_R(18),
        .REGMODE("NOREG"),
        .GSR("DISABLED"),
        .RESETMODE("ASYNC"),
        .CSDECODE_W("0b00"),
        .CSDECODE_R("0b00"),
        .ASYNC_RESET_RELEASE("SYNC")
    ) u0 (
        .CLKW(clk), .WE(gnd), .CSW1(gnd), .CSW0(gnd), .RST(gnd), .FULLI(gnd),
        .DI17(gnd), .DI16(gnd), .DI15(gnd), .DI14(gnd), .DI13(gnd),
        .DI12(gnd), .DI11(gnd), .DI10(gnd), .DI9(gnd),
        .DI8(gnd),  .DI7(gnd),  .DI6(gnd),  .DI5(gnd),
        .DI4(gnd),  .DI3(gnd),  .DI2(gnd),  .DI1(gnd),  .DI0(gnd),
        .CLKR(clk), .RE(gnd), .ORE(gnd), .CSR1(gnd), .CSR0(gnd), .RPRST(gnd), .EMPTYI(gnd),
        .DO17(q_w[17]), .DO16(q_w[16]), .DO15(q_w[15]), .DO14(q_w[14]),
        .DO13(q_w[13]), .DO12(q_w[12]), .DO11(q_w[11]), .DO10(q_w[10]),
        .DO9(q_w[9]),   .DO8(q_w[8]),   .DO7(q_w[7]),   .DO6(q_w[6]),
        .DO5(q_w[5]),   .DO4(q_w[4]),   .DO3(q_w[3]),   .DO2(q_w[2]),
        .DO1(q_w[1]),   .DO0(q_w[0]),
        .EF(ef_w), .AEF(aef_w), .AFF(af_w), .FF(ff_w)
    );
    reg out0_r;
    always @(posedge clk) out0_r <= ef_w ^ ff_w ^ ^q_w;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    targets.append(Target(
        name="fifo8kb_x18",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=internal_pin_list,
    ))

    return targets


def build_rom_targets() -> list[Target]:
    """Distributed ROM primitives."""
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 2)

    internal_pin_list = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("out0", ops[0], "out"),
    ]

    rom_prims = [
        ("rom16x1a",  "ROM16X1A",  4, "0x0000"),
        ("rom32x1a",  "ROM32X1A",  5, "0x00000000"),
        ("rom64x1a",  "ROM64X1A",  6, "0x0000000000000000"),
        ("rom128x1a", "ROM128X1A", 7, "0x00000000000000000000000000000000"),
        ("rom256x1a", "ROM256X1A", 8, "0x" + "0" * 64),
    ]

    for short_name, prim, addr_w, initval in rom_prims:
        addr_lines = "\n".join(
            f"        .AD{i}(gnd)," for i in range(addr_w)
        )
        vlog = f"""\
    wire gnd = 1'b0;
    wire do_w;
    {prim} #(.initval("{initval}")) u0 (
{addr_lines}
        .DO0(do_w)
    );
    reg out0_r;
    always @(posedge clk) out0_r <= do_w;
    assign out0 = out0_r;
"""
        ports_decl = "    input wire clk,\n    output wire out0"
        targets.append(Target(
            name=short_name,
            verilog=verilog_module(ports_decl, vlog),
            bank=bank,
            lpf_pins=internal_pin_list,
        ))

    return targets


def build_efb_targets() -> list[Target]:
    """EFB (embedded function block) — all non-empty subsets of {I2C1,I2C2,SPI,TC,UFM}."""
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 2)

    # I2C dedicated pins on LCMXO2-1200HC TQFP100:
    #   I2C1 SCL = pin 86 (site SCL/PCLKT0_0)
    #   I2C1 SDA = pin 85 (site SDA/PCLKC0_0)
    #   I2C2 SCL = pin 84, I2C2 SDA = pin 83
    # PAR enforces these locations — LPF must match exactly.
    internal_pin_list = [
        lpf_pin_entry("clk",      ck),
        lpf_pin_entry("out0",     ops[0], "out"),
        lpf_pin_entry("i2c1_scl", 86),
        lpf_pin_entry("i2c1_sda", 85),
        lpf_pin_entry("i2c2_scl", 84),
        lpf_pin_entry("i2c2_sda", 83),
    ]

    features = ["I2C1", "I2C2", "SPI", "TC", "UFM"]

    def subset_name(subset):
        return "efb_" + "_".join(f.lower() for f in subset)

    def make_efb_vlog(subset, spi_mode=None):
        enabled = set(subset)

        # SPI needs an explicit mode param
        spi_mode_param = ""
        if "SPI" in enabled:
            m = spi_mode or "SLAVE"
            spi_mode_param = f'\n        .SPI_MODE("{m}"),'

        param_lines = []
        for feat in features:
            val = "ENABLED" if feat in enabled else "DISABLED"
            param_lines.append(f'        .EFB_{feat}("{val}")')
        if spi_mode_param:
            param_lines.append(f'        .SPI_MODE("{spi_mode or "SLAVE"}")')
        param_lines.append('        .EFB_WB_CLK_FREQ("100.0")')
        params = ",\n".join(param_lines)

        # Connect I2C pins only when the I2C controller is enabled.
        # When disabled, tie inputs to gnd — do NOT expose them as module ports
        # because PAR will force the ports to the dedicated I2C pin sites (83-86)
        # even if the controller is disabled.
        i2c1_scl_s = "i2c1_scl" if "I2C1" in enabled else "gnd"
        i2c1_sda_s = "i2c1_sda" if "I2C1" in enabled else "gnd"
        i2c2_scl_s = "i2c2_scl" if "I2C2" in enabled else "gnd"
        i2c2_sda_s = "i2c2_sda" if "I2C2" in enabled else "gnd"

        return f"""\
    wire gnd = 1'b0;
    wire wbacko_w;
    wire [7:0] wbdato_w;
    EFB #(
{params}
    ) u0 (
        .WBCLKI(clk),
        .WBRSTI(gnd),
        .WBCYCI(gnd),
        .WBSTBI(gnd),
        .WBWEI(gnd),
        .WBADRI7(gnd), .WBADRI6(gnd), .WBADRI5(gnd), .WBADRI4(gnd),
        .WBADRI3(gnd), .WBADRI2(gnd), .WBADRI1(gnd), .WBADRI0(gnd),
        .WBDATI7(gnd), .WBDATI6(gnd), .WBDATI5(gnd), .WBDATI4(gnd),
        .WBDATI3(gnd), .WBDATI2(gnd), .WBDATI1(gnd), .WBDATI0(gnd),
        .PLL0DATI7(gnd), .PLL0DATI6(gnd), .PLL0DATI5(gnd), .PLL0DATI4(gnd),
        .PLL0DATI3(gnd), .PLL0DATI2(gnd), .PLL0DATI1(gnd), .PLL0DATI0(gnd),
        .PLL0ACKI(gnd),
        .PLL1DATI7(gnd), .PLL1DATI6(gnd), .PLL1DATI5(gnd), .PLL1DATI4(gnd),
        .PLL1DATI3(gnd), .PLL1DATI2(gnd), .PLL1DATI1(gnd), .PLL1DATI0(gnd),
        .PLL1ACKI(gnd),
        .I2C1SCLI({i2c1_scl_s}), .I2C1SDAI({i2c1_sda_s}),
        .I2C2SCLI({i2c2_scl_s}), .I2C2SDAI({i2c2_sda_s}),
        .SPISCKI(gnd), .SPIMISOI(gnd), .SPIMOSII(gnd), .SPISCSN(gnd),
        .TCCLKI(gnd), .TCRSTN(gnd), .TCIC(gnd),
        .UFMSN(gnd),
        .WBDATO7(wbdato_w[7]), .WBDATO6(wbdato_w[6]),
        .WBDATO5(wbdato_w[5]), .WBDATO4(wbdato_w[4]),
        .WBDATO3(wbdato_w[3]), .WBDATO2(wbdato_w[2]),
        .WBDATO1(wbdato_w[1]), .WBDATO0(wbdato_w[0]),
        .WBACKO(wbacko_w)
    );
    reg out0_r;
    always @(posedge clk) out0_r <= wbacko_w ^ ^wbdato_w;
    assign out0 = out0_r;
"""

    def make_efb_ports_and_pins(subset):
        """Return (ports_decl, lpf_pin_list) with only needed I2C ports.
        Only expose i2c1/i2c2 ports when those controllers are enabled;
        PAR forces I2C-connected ports to the dedicated I2C pin sites."""
        has_i2c1 = "I2C1" in subset
        has_i2c2 = "I2C2" in subset
        port_parts = ["    input wire clk"]
        pins = [
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("out0", ops[0], "out"),
        ]
        if has_i2c1:
            port_parts.append("    input wire i2c1_scl, i2c1_sda")
            pins.append(lpf_pin_entry("i2c1_scl", 86))
            pins.append(lpf_pin_entry("i2c1_sda", 85))
        if has_i2c2:
            port_parts.append("    input wire i2c2_scl, i2c2_sda")
            pins.append(lpf_pin_entry("i2c2_scl", 84))
            pins.append(lpf_pin_entry("i2c2_sda", 83))
        port_parts.append("    output wire out0")
        return ",\n".join(port_parts), pins

    # All 31 non-empty subsets
    for r in range(1, len(features) + 1):
        for subset in itertools.combinations(features, r):
            name = subset_name(subset)
            ports_decl, pin_list = make_efb_ports_and_pins(subset)
            targets.append(Target(
                name=name,
                verilog=verilog_module(ports_decl, make_efb_vlog(subset)),
                bank=bank,
                lpf_pins=pin_list,
            ))
            # EFB SPI master fuzz target is not possible:
            # Diamond MAP error: "MASTER_SPI_PORT preference cannot be set to DISABLE
            # when the SPI master interface is used in the design." The SPI master
            # requires physical SPI pins — not fuzzable in isolation.

    return targets


def build_jtag_targets() -> list[Target]:
    """JTAG — uses dedicated internal JTAG pins."""
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 2)

    vlog = f"""\
    wire gnd = 1'b0;
    wire jce1_w, jshift_w;
    JTAGF #(.ER1("ENABLED"), .ER2("DISABLED")) u0 (
        .TCK(), .TMS(), .TDI(), .JTDO1(gnd), .JTDO2(gnd),
        .TDO(), .JTCK(), .JTDI(), .JSHIFT(jshift_w), .JUPDATE(), .JRSTN(),
        .JCE1(jce1_w), .JCE2(), .JRTI1(), .JRTI2()
    );
    reg out0_r;
    always @(posedge clk) out0_r <= jce1_w;
    assign out0 = out0_r;
"""
    ports_decl = "    input wire clk,\n    output wire out0"
    return [Target(
        name="jtagf",
        verilog=verilog_module(ports_decl, vlog),
        bank=bank,
        lpf_pins=[
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("out0", ops[0], "out"),
        ],
    )]


def build_hardblock_targets() -> list[Target]:
    """Other hard block primitives: GSR, SGSR, TSALL, PUR, START, SEDFA, SEDFB, PG, PCNTR."""
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 4)

    internal_pin_list = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("out0", ops[0], "out"),
    ]
    ports_decl = "    input wire clk,\n    output wire out0"

    # GSR — global set/reset
    vlog = f"""\
    wire gnd = 1'b0;
    GSR u0 (.GSR(gnd));
    reg out0_r;
    always @(posedge clk) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
    targets.append(Target(name="gsr_inst", verilog=verilog_module(ports_decl, vlog),
                          bank=bank, lpf_pins=internal_pin_list))

    # SGSR — synchronous GSR
    vlog = f"""\
    wire gnd = 1'b0;
    SGSR u0 (.GSR(gnd), .CLK(clk));
    reg out0_r;
    always @(posedge clk) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
    targets.append(Target(name="sgsr_inst", verilog=verilog_module(ports_decl, vlog),
                          bank=bank, lpf_pins=internal_pin_list))

    # TSALL — tristate all outputs
    vlog = f"""\
    wire gnd = 1'b0;
    TSALL u0 (.TSALL(gnd));
    reg out0_r;
    always @(posedge clk) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
    targets.append(Target(name="tsall_inst", verilog=verilog_module(ports_decl, vlog),
                          bank=bank, lpf_pins=internal_pin_list))

    # PUR — power-up reset
    vlog = f"""\
    wire gnd = 1'b0;
    PUR #(.RST_PULSE("SYNC")) u0 (.PUR(gnd));
    reg out0_r;
    always @(posedge clk) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
    targets.append(Target(name="pur_inst", verilog=verilog_module(ports_decl, vlog),
                          bank=bank, lpf_pins=internal_pin_list))

    # START — configuration done / startup
    vlog = f"""\
    START u0 (.STARTCLK(clk));
    reg out0_r;
    always @(posedge clk) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
    targets.append(Target(name="start_inst", verilog=verilog_module(ports_decl, vlog),
                          bank=bank, lpf_pins=internal_pin_list))

    # SEDFA — SED with fabric outputs
    vlog = f"""\
    wire gnd = 1'b0;
    wire sederr_w, seddone_w, sedinprog_w, sedclkout_w;
    SEDFA u0 (
        .SEDSTDBY(gnd), .SEDENABLE(gnd), .SEDSTART(gnd), .SEDFRCERR(gnd),
        .SEDERR(sederr_w), .SEDDONE(seddone_w), .SEDINPROG(sedinprog_w), .SEDCLKOUT(sedclkout_w)
    );
    reg out0_r;
    always @(posedge clk) out0_r <= sederr_w ^ seddone_w ^ sedinprog_w;
    assign out0 = out0_r;
"""
    targets.append(Target(name="sedfa_inst", verilog=verilog_module(ports_decl, vlog),
                          bank=bank, lpf_pins=internal_pin_list))

    # SEDFB — SED without fabric inputs
    vlog = f"""\
    wire sederr_w, seddone_w, sedinprog_w, sedclkout_w;
    SEDFB u0 (
        .SEDERR(sederr_w), .SEDDONE(seddone_w), .SEDINPROG(sedinprog_w), .SEDCLKOUT(sedclkout_w)
    );
    reg out0_r;
    always @(posedge clk) out0_r <= sederr_w ^ seddone_w ^ sedinprog_w;
    assign out0 = out0_r;
"""
    targets.append(Target(name="sedfb_inst", verilog=verilog_module(ports_decl, vlog),
                          bank=bank, lpf_pins=internal_pin_list))

    # PG — SKIPPED
    # Power Guard D input must be driven by an IO buffer (pad), not fabric logic.
    # Diamond MAP: "Power Guard component cannot be driven by component i1."
    # PG is documented by prjtrellis. Skip as standalone fuzz target.
    # (target not appended)

    # PCNTR — power controller
    # USERSTDBY cannot be tied to a constant — must be driven from a togglable input pin.
    pcntr_ports_decl = "    input wire clk, input wire stdby_in,\n    output wire out0"
    pcntr_pin_list = [
        lpf_pin_entry("clk",      ck),
        lpf_pin_entry("stdby_in", BANK_PINS[bank][6]),
        lpf_pin_entry("out0",     ops[0], "out"),
    ]
    vlog = f"""\
    wire gnd = 1'b0;
    wire stdby_w, stop_w, sflag_w;
    PCNTR u0 (
        .CLK(clk), .USERTIMEOUT(gnd), .USERSTDBY(stdby_in), .CLRFLAG(gnd),
        .CFGWAKE(gnd), .CFGSTDBY(gnd),
        .STDBY(stdby_w), .STOP(stop_w), .SFLAG(sflag_w)
    );
    reg out0_r;
    always @(posedge clk) out0_r <= stdby_w ^ stop_w ^ sflag_w;
    assign out0 = out0_r;
"""
    targets.append(Target(name="pcntr_inst", verilog=verilog_module(pcntr_ports_decl, vlog),
                          bank=bank, lpf_pins=pcntr_pin_list))

    return targets


def build_ccu2d_targets() -> list[Target]:
    """CCU2D carry-chain primitives."""
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 4)

    ports_decl = "    input wire clk, input wire a, input wire b,\n    output wire out_s, out_co"
    pin_list = [
        lpf_pin_entry("clk",   ck),
        lpf_pin_entry("a",     data_pin(bank, 1)),
        lpf_pin_entry("b",     data_pin(bank, 2)),
        lpf_pin_entry("out_s", ops[0], "out"),
        lpf_pin_entry("out_co",ops[1], "out"),
    ]

    def ccu2d_vlog(init0: str, init1: str, inject0: str, inject1: str):
        # COUT must chain directly into next CCU2D CIN — cannot drive fabric FF.
        # Use two CCU2D cells: u0.COUT → u1.CIN. Register S0/S1 outputs only.
        return f"""\
    wire gnd = 1'b0;
    wire s0_w, s1_w, cout_w, s2_w, s3_w;
    CCU2D #(
        .INIT0(16'h{init0}),
        .INIT1(16'h{init1}),
        .INJECT1_0("{inject0}"),
        .INJECT1_1("{inject1}")
    ) u0 (
        .CIN(gnd),
        .A0(a), .B0(b), .C0(gnd), .D0(gnd),
        .A1(a), .B1(b), .C1(gnd), .D1(gnd),
        .S0(s0_w), .S1(s1_w), .COUT(cout_w)
    );
    CCU2D #(
        .INIT0(16'h{init0}),
        .INIT1(16'h{init1}),
        .INJECT1_0("{inject0}"),
        .INJECT1_1("{inject1}")
    ) u1 (
        .CIN(cout_w),
        .A0(a), .B0(b), .C0(gnd), .D0(gnd),
        .A1(a), .B1(b), .C1(gnd), .D1(gnd),
        .S0(s2_w), .S1(s3_w), .COUT()
    );
    reg [1:0] q;
    always @(posedge clk) q <= {{s3_w ^ s2_w, s1_w ^ s0_w}};
    assign {{out_co, out_s}} = q;
"""

    targets.append(Target(
        name="ccu2d_add",
        verilog=verilog_module(ports_decl, ccu2d_vlog("0666", "0666", "YES", "YES")),
        bank=bank,
        lpf_pins=pin_list,
    ))
    targets.append(Target(
        name="ccu2d_sub",
        verilog=verilog_module(ports_decl, ccu2d_vlog("0999", "0999", "YES", "YES")),
        bank=bank,
        lpf_pins=pin_list,
    ))
    targets.append(Target(
        name="ccu2d_logic",
        verilog=verilog_module(ports_decl, ccu2d_vlog("6996", "6996", "NO", "NO")),
        bank=bank,
        lpf_pins=pin_list,
    ))

    return targets


def build_highlevel_targets() -> list[Target]:
    """High-level synthesis constructs that test attribute / inference behaviour."""
    targets = []

    def hl(name: str, verilog: str, bank: int = 0, lpf_pins=None):
        t = Target(name=name, verilog=verilog, bank=bank, lpf_pins=lpf_pins, highlevel=True)
        return t

    for bank in [0, 1]:
        ck  = clk_pin(bank)
        d0  = data_pin(bank, 1)
        ops = out_pins(bank, 4)

        base_pins = [
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("d",    d0),
            lpf_pin_entry("q",    ops[0], "out"),
        ]

        # syn_useioff — posedge register
        vlog = """\
module fuzz (
    input  wire clk,
    input  wire d,
    output reg  q
);
    (* syn_useioff = 1 *)
    always @(posedge clk) q <= d;
endmodule
"""
        targets.append(hl(f"syn_useioff_posedge_bank{bank}", vlog, bank, base_pins))

        # syn_useioff with async reset
        rst_pin  = data_pin(bank, 2)
        rst_pins = base_pins + [lpf_pin_entry("rst", rst_pin)]
        vlog = """\
module fuzz (
    input  wire clk,
    input  wire d,
    input  wire rst,
    output reg  q
);
    (* syn_useioff = 1 *)
    always @(posedge clk or posedge rst)
        if (rst) q <= 1'b0;
        else     q <= d;
endmodule
"""
        targets.append(hl(f"syn_useioff_with_rst_bank{bank}", vlog, bank, rst_pins))

        # inferred DDR
        d1      = data_pin(bank, 2)
        ddr_pins = [
            lpf_pin_entry("clk",   ck),
            lpf_pin_entry("d",     d0),
            lpf_pin_entry("q_rise",ops[0], "out"),
            lpf_pin_entry("q_fall",ops[1], "out"),
        ]
        vlog = """\
module fuzz (
    input  wire clk,
    input  wire d,
    output reg  q_rise,
    output reg  q_fall
);
    always @(posedge clk) q_rise <= d;
    always @(negedge clk) q_fall <= d;
endmodule
"""
        targets.append(hl(f"inferred_ddr_bank{bank}", vlog, bank, ddr_pins))

    # syn_keep wire (bank 0)
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 4)
    vlog = """\
module fuzz (
    input  wire clk,
    input  wire a,
    input  wire b,
    output reg  out0
);
    (* syn_keep = 1 *) wire w;
    assign w = a ^ b;
    always @(posedge clk) out0 <= w;
endmodule
"""
    keep_pins = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("a",    data_pin(bank, 1)),
        lpf_pin_entry("b",    data_pin(bank, 2)),
        lpf_pin_entry("out0", ops[0], "out"),
    ]
    targets.append(hl("syn_keep_wire", vlog, bank, keep_pins))

    # Inferred BRAMs
    for (width, depth, name) in [(8, 256, "8bit"), (16, 256, "16bit"), (18, 256, "18bit")]:
        addr_w = 8
        bram_pins = [
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("out0", ops[0], "out"),
        ]
        vlog = f"""\
module fuzz (
    input  wire clk,
    output reg  out0
);
    reg [{width-1}:0] mem [0:{depth-1}];
    reg [7:0] addr;
    reg [{width-1}:0] dout;
    always @(posedge clk) begin
        addr <= addr + 1'b1;
        dout <= mem[addr];
    end
    always @(posedge clk) out0 <= ^dout;
endmodule
"""
        targets.append(hl(f"inferred_bram_{name}", vlog, bank, bram_pins))

    # Inferred shift registers
    for length in [8, 16]:
        shreg_pins = [
            lpf_pin_entry("clk",  ck),
            lpf_pin_entry("d",    data_pin(bank, 1)),
            lpf_pin_entry("out0", ops[0], "out"),
        ]
        vlog = f"""\
module fuzz (
    input  wire clk,
    input  wire d,
    output wire out0
);
    reg [{length-1}:0] shreg;
    always @(posedge clk) shreg <= {{shreg[{length-2}:0], d}};
    assign out0 = shreg[{length-1}];
endmodule
"""
        targets.append(hl(f"inferred_shreg_{length}", vlog, bank, shreg_pins))

    # EFB via defparam (SPI slave)
    efb_pins = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("out0", ops[0], "out"),
    ]
    vlog = """\
module fuzz (
    input  wire clk,
    output reg  out0
);
    wire gnd = 1'b0;
    wire wbacko_w;
    wire [7:0] wbdato_w;
    EFB u_efb (
        .WBCLKI(clk), .WBRSTI(gnd), .WBCYCI(gnd), .WBSTBI(gnd), .WBWEI(gnd),
        .WBADRI7(gnd), .WBADRI6(gnd), .WBADRI5(gnd), .WBADRI4(gnd),
        .WBADRI3(gnd), .WBADRI2(gnd), .WBADRI1(gnd), .WBADRI0(gnd),
        .WBDATI7(gnd), .WBDATI6(gnd), .WBDATI5(gnd), .WBDATI4(gnd),
        .WBDATI3(gnd), .WBDATI2(gnd), .WBDATI1(gnd), .WBDATI0(gnd),
        .PLL0DATI7(gnd), .PLL0DATI6(gnd), .PLL0DATI5(gnd), .PLL0DATI4(gnd),
        .PLL0DATI3(gnd), .PLL0DATI2(gnd), .PLL0DATI1(gnd), .PLL0DATI0(gnd), .PLL0ACKI(gnd),
        .PLL1DATI7(gnd), .PLL1DATI6(gnd), .PLL1DATI5(gnd), .PLL1DATI4(gnd),
        .PLL1DATI3(gnd), .PLL1DATI2(gnd), .PLL1DATI1(gnd), .PLL1DATI0(gnd), .PLL1ACKI(gnd),
        .I2C1SCLI(gnd), .I2C1SDAI(gnd), .I2C2SCLI(gnd), .I2C2SDAI(gnd),
        .SPISCKI(gnd), .SPIMISOI(gnd), .SPIMOSII(gnd), .SPISCSN(gnd),
        .TCCLKI(gnd), .TCRSTN(gnd), .TCIC(gnd), .UFMSN(gnd),
        .WBDATO7(wbdato_w[7]), .WBDATO6(wbdato_w[6]),
        .WBDATO5(wbdato_w[5]), .WBDATO4(wbdato_w[4]),
        .WBDATO3(wbdato_w[3]), .WBDATO2(wbdato_w[2]),
        .WBDATO1(wbdato_w[1]), .WBDATO0(wbdato_w[0]),
        .WBACKO(wbacko_w)
    );
    defparam u_efb.EFB_SPI = "ENABLED";
    defparam u_efb.SPI_MODE = "SLAVE";
    defparam u_efb.EFB_I2C1 = "DISABLED";
    defparam u_efb.EFB_I2C2 = "DISABLED";
    defparam u_efb.EFB_TC = "DISABLED";
    defparam u_efb.EFB_UFM = "DISABLED";
    defparam u_efb.EFB_WB_CLK_FREQ = "100.0";
    always @(posedge clk) out0 <= wbacko_w ^ ^wbdato_w;
endmodule
"""
    targets.append(hl("efb_spi_slave_defparam", vlog, bank, efb_pins))

    # EFB SPI master via defparam
    # Requires SYSCONFIG MASTER_SPI_PORT=ENABLE in LPF; Diamond MAP rejects the
    # design if this is left at the default DISABLE when SPI_MODE="MASTER".
    vlog = vlog.replace('SPI_MODE = "SLAVE"', 'SPI_MODE = "MASTER"')
    vlog = vlog.replace('efb_spi_slave_defparam', 'efb_spi_master_defparam')
    master_t = hl("efb_spi_master_defparam", vlog, bank, efb_pins)
    master_t.lpf_extra = 'SYSCONFIG MASTER_SPI_PORT=ENABLE ;'
    targets.append(master_t)

    # OSCH 133 MHz
    vlog = """\
module fuzz (
    input  wire clk,
    output reg  out0
);
    wire gnd = 1'b0;
    wire osc_w;
    OSCH #(.NOM_FREQ("133.00")) u0 (.STDBY(gnd), .OSC(osc_w));
    always @(posedge osc_w) out0 <= ~out0;
endmodule
"""
    targets.append(hl("osch_freq_133mhz", vlog, bank, [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("out0", ops[0], "out"),
    ]))

    # PLL basic via defparam
    vlog = """\
module fuzz (
    input  wire clk,
    output reg  out0
);
    wire gnd = 1'b0;
    wire vcc = 1'b1;
    wire clkop_w, lock_w;
    EHXPLLJ u0 (
        .CLKI(clk), .CLKFB(clkop_w), .RST(gnd), .STDBY(gnd), .PLLWAKESYNC(gnd),
        .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd), .PHASESTEP(gnd), .LOADREG(gnd),
        .RESETM(gnd), .RESETC(gnd), .RESETD(gnd),
        .ENCLKOP(vcc), .ENCLKOS(gnd), .ENCLKOS2(gnd), .ENCLKOS3(gnd),
        .PLLCLK(gnd), .PLLRST(gnd), .PLLSTB(gnd), .PLLWE(gnd),
        .PLLADDR4(gnd), .PLLADDR3(gnd), .PLLADDR2(gnd), .PLLADDR1(gnd), .PLLADDR0(gnd),
        .PLLDATI7(gnd), .PLLDATI6(gnd), .PLLDATI5(gnd), .PLLDATI4(gnd),
        .PLLDATI3(gnd), .PLLDATI2(gnd), .PLLDATI1(gnd), .PLLDATI0(gnd),
        .CLKOP(clkop_w), .LOCK(lock_w)
    );
    defparam u0.CLKI_DIV   = 1;
    defparam u0.CLKFB_DIV  = 1;
    defparam u0.CLKOP_DIV  = 1;
    defparam u0.CLKOP_ENABLE = "ENABLED";
    defparam u0.FEEDBK_PATH  = "CLKOP";
    always @(posedge clkop_w) out0 <= lock_w;
endmodule
"""
    targets.append(hl("pll_basic_defparam", vlog, bank, [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("out0", ops[0], "out"),
    ]))

    return targets


# ---------------------------------------------------------------------------
# Parameter sweep targets — full enumeration of every configurable attribute
# ---------------------------------------------------------------------------

# IO_TYPE values legal per direction on TQFP100.
# prjtrellis 051-pio_attrs sweeps these exhaustively.
PIO_IO_TYPES_INPUT = [
    "LVCMOS33", "LVCMOS25", "LVCMOS18", "LVCMOS15", "LVCMOS12",
    "LVCMOS33D", "LVCMOS25D",
    "PCI33", "LVTTL33", "LVTTL33D",
    "LVPECL33", "LVPECL33E",
    "LVDS25", "LVDS25E", "BLVDS25",
    "MLVDS25", "MLVDS25E",
    "RSDS25", "RSDS25E",
    "MIPI",
    "HSTL15_I", "HSTL18_I",
    "SSTL25_I", "SSTL18_I", "SSTL15",
]
PIO_IO_TYPES_OUTPUT = [
    "LVCMOS33", "LVCMOS25", "LVCMOS18", "LVCMOS15", "LVCMOS12",
    "LVCMOS33D", "LVCMOS25D",
    "LVTTL33", "LVTTL33D",
    "LVDS25", "LVDS25E", "BLVDS25",
    "MLVDS25", "MLVDS25E",
    "RSDS25", "RSDS25E",
    "HSTL15_I", "HSTL18_I",
    "SSTL25_I", "SSTL18_I", "SSTL15",
]

# OSCH NOM_FREQ values (all 56 from prjtrellis 102-oscg)
OSCH_FREQS = [
    "2.08",  "4.16",  "8.31",  "16.63",
    "2.15",  "4.29",  "8.58",  "17.73",
    "2.22",  "4.43",  "8.87",  "19.00",
    "2.29",  "4.59",  "9.17",  "20.46",
    "2.38",  "4.75",  "9.50",  "22.17",
    "2.46",  "4.93",  "9.85",  "24.18",
    "2.56",  "5.12", "10.23",  "26.60",
    "2.66",  "5.32", "10.64",  "29.56",
    "2.77",  "5.54", "11.08",  "33.25",
    "2.89",  "5.78", "11.57",  "38.00",
    "3.02",  "6.05", "12.09",  "44.33",
    "3.17",  "6.33", "12.67",  "53.20",
    "3.33",  "6.65", "13.30",  "66.50",
    "3.50",  "7.00", "14.00",  "88.67",
    "3.69",  "7.39", "14.78", "133.00",
    "3.91",  "7.82", "15.65",
]

# SED CLK_FREQ values (55 + default from prjtrellis 105-sedfa)
SED_FREQS = [
    "2.08",  "4.16",  "8.31",  "16.63",
    "2.15",  "4.29",  "8.58",  "17.73",
    "2.22",  "4.43",  "8.87",  "19.00",
    "2.29",  "4.59",  "9.17",  "20.46",
    "2.38",  "4.75",  "9.50",  "22.17",
    "2.46",  "4.93",  "9.85",  "24.18",
    "2.56",  "5.12", "10.23",  "26.60",
    "2.66",  "5.32", "10.64",  "29.56",
    "2.77",  "5.54", "11.08",  "33.25",
    "2.89",  "5.78", "11.57",
    "3.02",  "6.05", "12.09",
    "3.17",  "6.33", "12.67",
    "3.33",  "6.65", "13.30",
    "3.50",  "7.00", "14.00",
    "3.69",  "7.39", "14.78",
    "3.91",  "7.82", "15.65",
]


def _safe_name(s: str) -> str:
    """Convert a parameter value to a safe directory-name fragment."""
    return s.replace(".", "p").replace("/", "_").replace(" ", "_").replace('"', "")


def build_pio_attr_sweep() -> list[Target]:
    """PIO attribute sweep — prjtrellis 051-pio_attrs equivalent.

    Per bank × per IO_TYPE, PULLMODE, SLEWRATE, DRIVE, HYSTERESIS, OPENDRAIN, CLAMP.
    Uses a single pin per target — the 'A' (first) data pin in each bank.
    """
    targets = []

    # IB / OB / BB — IO_TYPE sweep, one pin per bank
    for bank in [0, 1, 2]:
        ck  = clk_pin(bank)
        pin = data_pin(bank, 1)
        op  = out_pins(bank, 1)[0]

        # Input IO_TYPE sweep
        for iotype in PIO_IO_TYPES_INPUT:
            # Differential input types need a complementary pin — skip for simplicity
            # (we already have ilvds / lvdsob primitives)
            if iotype.endswith("D") or iotype in ("LVDS25", "LVDS25E", "BLVDS25",
                                                    "MLVDS25", "MLVDS25E", "RSDS25",
                                                    "RSDS25E", "LVPECL33", "LVPECL33E",
                                                    "MIPI"):
                continue
            sname = _safe_name(iotype)
            vlog = f"""\
    wire gnd = 1'b0;
    wire q_w;
    (* LOC="{pin}", IO_TYPE="{iotype}" *)
    IB u0 (.I(d), .O(q_w));
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
            targets.append(Target(
                name=f"pio_iotype_in_{sname}_bank{bank}",
                verilog=verilog_module(
                    f"    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    pin),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))

        # Output IO_TYPE sweep
        for iotype in PIO_IO_TYPES_OUTPUT:
            if iotype.endswith("D") or iotype in ("LVDS25", "LVDS25E", "BLVDS25",
                                                    "MLVDS25", "MLVDS25E", "RSDS25",
                                                    "RSDS25E"):
                continue
            sname = _safe_name(iotype)
            vlog = f"""\
    wire gnd = 1'b0;
    reg out0_r;
    (* LOC="{op}", IO_TYPE="{iotype}" *)
    OB u0 (.I(out0_r), .O(out0));
    always @(posedge clk) out0_r <= d;
"""
            targets.append(Target(
                name=f"pio_iotype_out_{sname}_bank{bank}",
                verilog=verilog_module(
                    f"    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    pin),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))

        # PULLMODE sweep (on input)
        for pull in ["UP", "DOWN", "NONE", "KEEPER", "FAILSAFE"]:
            vlog = f"""\
    wire q_w;
    (* LOC="{pin}", IO_TYPE="LVCMOS33", PULLMODE="{pull}" *)
    IB u0 (.I(d), .O(q_w));
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
            targets.append(Target(
                name=f"pio_pull_{pull.lower()}_bank{bank}",
                verilog=verilog_module(
                    f"    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    pin),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))

        # SLEWRATE sweep (on output)
        for slew in ["FAST", "SLOW"]:
            vlog = f"""\
    reg out0_r;
    (* LOC="{op}", IO_TYPE="LVCMOS33", SLEWRATE="{slew}" *)
    OB u0 (.I(out0_r), .O(out0));
    always @(posedge clk) out0_r <= d;
"""
            targets.append(Target(
                name=f"pio_slew_{slew.lower()}_bank{bank}",
                verilog=verilog_module(
                    f"    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    pin),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))

        # DRIVE sweep (on output) — 2/6 require LVCMOS12 per prjtrellis note
        for drive in ["2", "4", "6", "8", "12", "16", "24"]:
            iotype_for_drive = "LVCMOS12" if drive in ("2", "6") else "LVCMOS33"
            vlog = f"""\
    reg out0_r;
    (* LOC="{op}", IO_TYPE="{iotype_for_drive}", DRIVE={drive} *)
    OB u0 (.I(out0_r), .O(out0));
    always @(posedge clk) out0_r <= d;
"""
            targets.append(Target(
                name=f"pio_drive_{drive}ma_bank{bank}",
                verilog=verilog_module(
                    f"    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    pin),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))

        # HYSTERESIS sweep (on input)
        for hyst in ["SMALL", "LARGE"]:
            vlog = f"""\
    wire q_w;
    (* LOC="{pin}", IO_TYPE="LVCMOS33", HYSTERESIS="{hyst}" *)
    IB u0 (.I(d), .O(q_w));
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
            targets.append(Target(
                name=f"pio_hyst_{hyst.lower()}_bank{bank}",
                verilog=verilog_module(
                    f"    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    pin),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))

        # OPENDRAIN sweep (on output)
        for od in ["ON", "OFF"]:
            vlog = f"""\
    reg out0_r;
    (* LOC="{op}", IO_TYPE="LVCMOS33", OPENDRAIN="{od}" *)
    OB u0 (.I(out0_r), .O(out0));
    always @(posedge clk) out0_r <= d;
"""
            targets.append(Target(
                name=f"pio_od_{od.lower()}_bank{bank}",
                verilog=verilog_module(
                    f"    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    pin),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))

        # CLAMP sweep (on input) — only supported on bank 2 (bottom) for PCI/OFF
        if bank == 2:
            for clamp in ["PCI", "OFF"]:
                io_t = "LVCMOS33" if clamp == "OFF" else "PCI33"
                vlog = f"""\
    wire q_w;
    (* LOC="{pin}", IO_TYPE="{io_t}", CLAMP="{clamp}" *)
    IB u0 (.I(d), .O(q_w));
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
                targets.append(Target(
                    name=f"pio_clamp_{clamp.lower()}_bank{bank}",
                    verilog=verilog_module(
                        f"    input wire clk,\n    input wire d,\n    output wire out0",
                        vlog),
                    bank=bank,
                    lpf_pins=[
                        lpf_pin_entry("clk",  ck),
                        lpf_pin_entry("d",    pin),
                        lpf_pin_entry("out0", op, "out"),
                    ],
                ))

    return targets


def build_lut_ff_sweep() -> list[Target]:
    """LUT INIT and FF config sweep — prjtrellis 003-lut_init + 005-reg_config.

    LUT4: sweep all 16 single-bit-set INIT patterns (walking 1) + inverse + a few
    composite patterns. This verifies each bit of the 16-bit INIT word independently.

    FF: sweep REGSET(RESET/SET) × REGMODE(FF/LATCH) × GSR(ENABLED/DISABLED).
    """
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    d0   = data_pin(bank, 1)
    d1   = data_pin(bank, 2)
    d2   = data_pin(bank, 3)
    ops  = out_pins(bank, 4)

    # ── LUT4 INIT sweep ─────────────────────────────────────────────────────
    # Walking-1: set exactly one of the 16 init bits, verify bit-to-position mapping
    for bit in range(16):
        init_val = 1 << bit
        init_hex = f"16'h{init_val:04X}"
        vlog = f"""\
    wire out_w;
    LUT4 #(.init({init_hex})) u0 (.A(d), .B(d2), .C(d3), .D(1'b0), .Z(out_w));
    reg out0_r;
    always @(posedge clk) out0_r <= out_w;
    assign out0 = out0_r;
"""
        targets.append(Target(
            name=f"lut4_init_bit{bit:02d}",
            verilog=verilog_module(
                "    input wire clk,\n    input wire d,\n    input wire d2,\n    input wire d3,\n    output wire out0",
                vlog),
            bank=bank,
            lpf_pins=[
                lpf_pin_entry("clk", ck),
                lpf_pin_entry("d",   d0),
                lpf_pin_entry("d2",  d1),
                lpf_pin_entry("d3",  d2),
                lpf_pin_entry("out0", ops[0], "out"),
            ],
        ))

    # Walking-0: complement of each walking-1 (all bits set except one)
    for bit in range(16):
        init_val = 0xFFFF ^ (1 << bit)
        init_hex = f"16'h{init_val:04X}"
        vlog = f"""\
    wire out_w;
    LUT4 #(.init({init_hex})) u0 (.A(d), .B(d2), .C(d3), .D(1'b0), .Z(out_w));
    reg out0_r;
    always @(posedge clk) out0_r <= out_w;
    assign out0 = out0_r;
"""
        targets.append(Target(
            name=f"lut4_init_notbit{bit:02d}",
            verilog=verilog_module(
                "    input wire clk,\n    input wire d,\n    input wire d2,\n    input wire d3,\n    output wire out0",
                vlog),
            bank=bank,
            lpf_pins=[
                lpf_pin_entry("clk", ck),
                lpf_pin_entry("d",   d0),
                lpf_pin_entry("d2",  d1),
                lpf_pin_entry("d3",  d2),
                lpf_pin_entry("out0", ops[0], "out"),
            ],
        ))

    # Some useful composite patterns: AND4, OR4, XOR4, identity on each input
    lut_composites = {
        "and4":    "16'h8000",
        "or4":     "16'hFFFE",
        "xor4":    "16'h6996",
        "buf_a":   "16'hAAAA",
        "buf_b":   "16'hCCCC",
        "buf_c":   "16'hF0F0",
        "buf_d":   "16'hFF00",
        "nand4":   "16'h7FFF",
        "nor4":    "16'h0001",
        "xnor4":   "16'h9669",
        "mux2":    "16'hCACA",
        "maj3":    "16'hE8E8",
        "all0":    "16'h0000",
        "all1":    "16'hFFFF",
    }
    for name, init_hex in lut_composites.items():
        vlog = f"""\
    wire out_w;
    LUT4 #(.init({init_hex})) u0 (.A(d), .B(d2), .C(d3), .D(1'b0), .Z(out_w));
    reg out0_r;
    always @(posedge clk) out0_r <= out_w;
    assign out0 = out0_r;
"""
        targets.append(Target(
            name=f"lut4_{name}",
            verilog=verilog_module(
                "    input wire clk,\n    input wire d,\n    input wire d2,\n    input wire d3,\n    output wire out0",
                vlog),
            bank=bank,
            lpf_pins=[
                lpf_pin_entry("clk", ck),
                lpf_pin_entry("d",   d0),
                lpf_pin_entry("d2",  d1),
                lpf_pin_entry("d3",  d2),
                lpf_pin_entry("out0", ops[0], "out"),
            ],
        ))

    # ── FF config sweep ──────────────────────────────────────────────────────
    # Sweep FF primitives × GSR.
    # FD1S3AX: D,CK,Q (plain)    FD1S3BX: D,CK,PD,Q (async pre)
    # FD1S3DX: D,CK,CD,Q (async clr)   FD1S3IX: D,CK,CD,Q (async clr inv)
    # FD1S3JX: D,CK,PD,Q (async pre inv)
    # FD1P3AX: D,SP,CK,Q (CE only)  FD1P3DX: D,SP,CK,CD,Q (CE+clr)
    # FD1P3IX: D,SP,CK,CD,Q (CE+clr inv)  FD1P3JX: D,SP,CK,PD,Q (CE+pre)
    # Ports: (ports_str, rst_port or None, has_sp)
    for ff_prim, ff_desc, ports_str, has_sp in [
        ("FD1S3AX", "plain",        ".CK(clk), .D(d), .Q(q_w)",                            False),
        ("FD1S3BX", "async_pre",    ".CK(clk), .D(d), .PD(1'b0), .Q(q_w)",                 False),
        ("FD1S3DX", "async_clr",    ".CK(clk), .D(d), .CD(1'b0), .Q(q_w)",                 False),
        ("FD1S3JX", "async_pre_inv",".CK(clk), .D(d), .PD(1'b0), .Q(q_w)",                 False),
        ("FD1P3AX", "ce",           ".CK(clk), .D(d), .SP(1'b1), .Q(q_w)",                 True),
        ("FD1P3DX", "ce_async_clr", ".CK(clk), .D(d), .SP(1'b1), .CD(1'b0), .Q(q_w)",     True),
        ("FD1P3JX", "ce_async_pre", ".CK(clk), .D(d), .SP(1'b1), .PD(1'b0), .Q(q_w)",     True),
    ]:
        for gsr in ["ENABLED", "DISABLED"]:
            vlog = f"""\
    wire q_w;
    (* GSR="{gsr}" *)
    {ff_prim} u0 ({ports_str});
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
            targets.append(Target(
                name=f"ff_{ff_desc}_gsr{gsr.lower()[:3]}",
                verilog=verilog_module(
                    "    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    d0),
                    lpf_pin_entry("out0", ops[0], "out"),
                ],
            ))

    return targets


def build_osch_freq_sweep() -> list[Target]:
    """OSCH NOM_FREQ sweep — all 57 frequencies from prjtrellis 102-oscg."""
    targets = []
    bank = 0
    op   = out_pins(bank, 1)[0]
    for freq in OSCH_FREQS:
        freq_safe = _safe_name(freq)
        vlog = f"""\
    wire gnd = 1'b0;
    wire osc_w;
    OSCH #(.NOM_FREQ("{freq}")) u0 (.STDBY(gnd), .OSC(osc_w));
    reg out0_r;
    always @(posedge osc_w) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
        targets.append(Target(
            name=f"osch_freq_{freq_safe}",
            verilog=verilog_module(
                "    output wire out0",
                vlog),
            bank=bank,
            lpf_pins=[lpf_pin_entry("out0", op, "out")],
        ))
    return targets


def build_gsr_sweep() -> list[Target]:
    """GSR attribute sweep — SKIPPED.

    Diamond's GSR primitive has no Verilog parameters and no LPF attribute for
    GSRMODE/SYNCMODE — these are NCL-level structural bits only.
    prjtrellis 103-gsr uses NCL to set them, which we cannot replicate via Verilog.
    A single GSR instantiation already exists in build_hardblock_targets() as gsr_inst.
    """
    return []


def build_sed_sweep() -> list[Target]:
    """SEDFA attribute sweep — CLK_FREQ × CHECKALWAYS (prjtrellis 105-sedfa).

    SEDFB is identical in parameters; just one variant.
    """
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 3)
    for freq in SED_FREQS:
        freq_safe = _safe_name(freq)
        for ca in ["DISABLED", "ENABLED"]:
            ca_s = "en" if ca == "ENABLED" else "dis"
            vlog = f"""\
    wire gnd = 1'b0;
    wire sedout_w;
    SEDFA #(
        .SED_CLK_FREQ("{freq}"),
        .CHECKALWAYS("{ca}")
    ) u0 (
        .SEDENABLE(1'b1), .SEDSTDBY(gnd),
        .SEDFRCERR(gnd), .SEDSTART(gnd),
        .SEDDONE(sedout_w), .SEDERR(), .SEDINPROG(), .SEDCLKOUT()
    );
    reg out0_r;
    always @(posedge clk) out0_r <= sedout_w;
    assign out0 = out0_r;
"""
            targets.append(Target(
                name=f"sedfa_freq_{freq_safe}_ca{ca_s}",
                verilog=verilog_module(
                    "    input wire clk,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("out0", ops[0], "out"),
                ],
            ))
    return targets


def build_pcntr_sweep() -> list[Target]:
    """PCNTR attribute sweep — STDBYOPT × WAKEUP × TIMEOUT × POROFF × BGOFF."""
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    ops  = out_pins(bank, 2)
    # BGOFF=TRUE is rejected for LCMXO2-1200HC ("Unable to turn off Bandgap").
    # Keep BGOFF=FALSE always; sweep only the other 4 dimensions.
    for stdbyopt in ["USER_CFG", "USER", "CFG"]:
        for wakeup in ["USER", "CFG"]:
            for timeout in ["BYPASS", "USER", "COUNTER"]:
                for poroff in ["FALSE", "TRUE"]:
                    for bgoff in ["FALSE"]:
                        sname = (f"pcntr_stdby{_safe_name(stdbyopt)}_wake{wakeup.lower()}"
                                 f"_to{timeout.lower()}_por{poroff.lower()}_bg{bgoff.lower()}")
                        vlog = f"""\
    wire gnd = 1'b0;
    wire stdby_w, stop_w, sflag_w;
    PCNTR #(
        .STDBYOPT("{stdbyopt}"),
        .WAKEUP("{wakeup}"),
        .TIMEOUT("{timeout}"),
        .POROFF("{poroff}"),
        .BGOFF("{bgoff}")
    ) u0 (
        .CLK(clk), .USERSTDBY(d), .USERTIMEOUT(d), .CLRFLAG(d),
        .CFGWAKE(gnd), .CFGSTDBY(gnd),
        .STDBY(stdby_w), .STOP(stop_w), .SFLAG(sflag_w)
    );
    reg out0_r;
    always @(posedge clk) out0_r <= stdby_w ^ stop_w;
    assign out0 = out0_r;
"""
                        targets.append(Target(
                            name=sname,
                            verilog=verilog_module(
                                "    input wire clk,\n    input wire d,\n    output wire out0",
                                vlog),
                            bank=bank,
                            lpf_pins=[
                                lpf_pin_entry("clk",  ck),
                                lpf_pin_entry("d",    data_pin(bank, 1)),
                                lpf_pin_entry("out0", ops[0], "out"),
                            ],
                        ))
    return targets


def build_sysconfig_sweep() -> list[Target]:
    """SYSCONFIG attribute sweep — prjtrellis 140-sysconfig.

    SYSCONFIG goes in the LPF as a constraint, not in Verilog.
    Combine with an empty design (just GSR + FF to keep Diamond happy).
    """
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    d0   = data_pin(bank, 1)
    op   = out_pins(bank, 1)[0]

    # Minimal design: one FF, output driven to prevent optimisation
    base_vlog = """\
    wire gnd = 1'b0;
    wire q_w;
    FD1S3AX u0 (.CK(clk), .D(d), .Q(q_w));
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
    base_pins = [
        lpf_pin_entry("clk",  ck),
        lpf_pin_entry("d",    d0),
        lpf_pin_entry("out0", op, "out"),
    ]
    base_verilog = verilog_module(
        "    input wire clk,\n    input wire d,\n    output wire out0",
        base_vlog)

    for sdm in ["PROGRAMN", "DISABLE"]:
        for slave_spi in ["DISABLE", "ENABLE"]:
            for bg_reconfig in ["OFF", "ON"]:
                sname = (f"syscfg_sdm{_safe_name(sdm)}_slvspi{slave_spi.lower()}"
                         f"_bgrec{bg_reconfig.lower()}")
                # MASTER_SPI_PORT deliberately left at default DISABLE for these targets
                lpf_extra = (
                    f'SYSCONFIG SDM_PORT={sdm} '
                    f'SLAVE_SPI_PORT={slave_spi} '
                    f'BACKGROUND_RECONFIG={bg_reconfig} ;'
                )
                targets.append(Target(
                    name=sname,
                    verilog=base_verilog,
                    bank=bank,
                    lpf_pins=base_pins,
                    lpf_extra=lpf_extra,
                ))

    # Sweep MASTER_SPI_PORT separately (needs ENABLE in LPF)
    for master_spi in ["DISABLE", "ENABLE", "EFB_USER"]:
        sname = f"syscfg_mstspi_{master_spi.lower()}"
        lpf_extra = f'SYSCONFIG MASTER_SPI_PORT={master_spi} ;'
        if master_spi == "ENABLE":
            lpf_extra = 'SYSCONFIG MASTER_SPI_PORT=ENABLE ;'
        targets.append(Target(
            name=sname,
            verilog=base_verilog,
            bank=bank,
            lpf_pins=base_pins,
            lpf_extra=lpf_extra,
        ))

    # I2C_PORT
    for i2c in ["DISABLE", "ENABLE"]:
        sname = f"syscfg_i2c_{i2c.lower()}"
        lpf_extra = f'SYSCONFIG I2C_PORT={i2c} ;'
        targets.append(Target(
            name=sname,
            verilog=base_verilog,
            bank=bank,
            lpf_pins=base_pins,
            lpf_extra=lpf_extra,
        ))

    return targets


def build_pll_param_sweep() -> list[Target]:
    """EHXPLLJ parameter sweep — all numeric dividers and enum settings.

    prjtrellis 091-pll_config sweeps: CLKI_DIV, CLKFB_DIV, CLKOP/OS/OS2/OS3_DIV (1-128),
    CLKOP/OS_CPHASE (0-127), CLKOP/OS_FPHASE (0-7), plus all enum flags.

    We sweep dividers at key values (1,2,3,4,5,6,7,8,16,32,64,128) and CPHASE/FPHASE
    at every value. Enum flags get individual targets.
    """
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    op   = out_pins(bank, 1)[0]

    def pll_target(name: str, params: dict) -> Target:
        # Build param string; always include minimal required params.
        # intfb=True: use INT_DIVA internal feedback (CLKFB tied to gnd, no external loop).
        # Base: CLKI_DIV=1, CLKFB_DIV=1, CLKOP_DIV=1.
        # Always use FEEDBK_PATH=INT_DIVA with CLKFB=gnd. Diamond auto-routes
        # CLKINTFB→CLKFB for INT_DIVA mode, bypassing the external phase-check
        # that rejects FEEDBK_PATH=CLKOP ("phase shift should not be used as feedback").
        # The FEEDBK_PATH sweep target will explicitly test CLKOP and USERCLOCK paths.
        base = {
            "CLKI_DIV": 1, "CLKFB_DIV": 1, "CLKOP_DIV": 1,
            "CLKOP_ENABLE": '"ENABLED"',
            "FEEDBK_PATH": '"INT_DIVA"',
        }
        base.update(params)
        param_str = ",\n    ".join(f".{k}({v})" for k, v in base.items())
        # FEEDBK_PATH=CLKOP needs external feedback; all others use INT_DIVA with gnd
        feedbk = base.get("FEEDBK_PATH", '"INT_DIVA"')
        clkfb_conn = "clkop_w" if feedbk == '"CLKOP"' else "gnd"
        vlog = f"""\
    wire gnd = 1'b0;
    wire vcc = 1'b1;
    wire clkop_w, lock_w;
    EHXPLLJ #(
    {param_str}
    ) u0 (
        .CLKI(clk), .CLKFB({clkfb_conn}), .RST(gnd), .STDBY(gnd), .PLLWAKESYNC(gnd),
        .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd), .PHASESTEP(gnd), .LOADREG(gnd),
        .RESETM(gnd), .RESETC(gnd), .RESETD(gnd),
        .ENCLKOP(vcc), .ENCLKOS(gnd), .ENCLKOS2(gnd), .ENCLKOS3(gnd),
        .PLLCLK(gnd), .PLLRST(gnd), .PLLSTB(gnd), .PLLWE(gnd),
        .PLLADDR4(gnd), .PLLADDR3(gnd), .PLLADDR2(gnd), .PLLADDR1(gnd), .PLLADDR0(gnd),
        .PLLDATI7(gnd), .PLLDATI6(gnd), .PLLDATI5(gnd), .PLLDATI4(gnd),
        .PLLDATI3(gnd), .PLLDATI2(gnd), .PLLDATI1(gnd), .PLLDATI0(gnd),
        .CLKOP(clkop_w), .LOCK(lock_w)
    );
    reg out0_r;
    always @(posedge clkop_w) out0_r <= lock_w;
    assign out0 = out0_r;
"""
        # Compute expected CLKOP frequency so Diamond can validate the phase relationship.
        # VCO = 100 MHz × CLKFB_DIV × CLKOP_DIV / CLKI_DIV; CLKOP = VCO / CLKOP_DIV.
        # All reduce to: CLKOP = 100 × CLKFB_DIV / CLKI_DIV.
        clki_div = base.get("CLKI_DIV", 1)
        clkfb_div = base.get("CLKFB_DIV", 1)
        clkop_freq = 100.0 * clkfb_div / clki_div
        return Target(
            name=f"pll_{name}",
            verilog=verilog_module("    input wire clk,\n    output wire out0", vlog),
            bank=bank,
            lpf_pins=[lpf_pin_entry("clk", ck), lpf_pin_entry("out0", op, "out")],
            lpf_extra=f'FREQUENCY NET "clkop_w" {clkop_freq:.6f} MHz;\n',
        )

    # Divider sweeps skipped — Diamond rejects CLKOP_DIV != 1 with:
    # "output CLKOP with N degree phase shift should not be used as the feedback signal"
    # This is a Diamond PLL DRC that fires for any divider that creates an inherent
    # phase offset, regardless of FEEDBK_PATH or frequency constraints.
    # Only CLKOP_DIV=1 (the default base) works standalone without a full SDC flow.

    # CPHASE and FPHASE sweeps skipped — Diamond rejects CPHASE != 0 with:
    # "output CLKOP with N degree phase shift should not be used as the feedback signal".
    # Phase shift = CLKOP_CPHASE × (360 / CLKOP_DIV). With DIV=1, even CPHASE=1 = 360°.
    # With DIV>1, the division itself creates a phase shift error. No standalone config works.

    # FEEDBK_PATH enum
    for fp in ["CLKOP", "CLKOS", "CLKOS2", "CLKOS3",
               "INT_DIVA", "INT_DIVB", "INT_DIVC", "INT_DIVD", "USERCLOCK"]:
        targets.append(pll_target(f"feedbk_{_safe_name(fp)}",
                                  {"FEEDBK_PATH": f'"{fp}"'}))

    # CLKOP_TRIM_POL + TRIM_DELAY (integer, not string)
    for pol in ["RISING", "FALLING"]:
        for delay in [0, 1, 2, 4]:
            targets.append(pll_target(
                f"clkop_trim_{pol.lower()}_d{delay}",
                {"CLKOP_TRIM_POL": f'"{pol}"', "CLKOP_TRIM_DELAY": delay}))

    # Boolean flags — only those that actually exist in EHXPLLJ
    for flag in ["STDBY_ENABLE", "DPHASE_SOURCE", "INTFB_WAKE", "PLLRST_ENA", "MRST_ENA",
                 "PLL_USE_WB", "FRACN_ENABLE"]:
        for val in ["ENABLED", "DISABLED"]:
            targets.append(pll_target(
                f"{flag.lower()}_{val.lower()}",
                {flag: f'"{val}"'}))

    # OUTDIVIDER_MUXA/B/C/D (all valid in Diamond)
    for mux, choices in [("OUTDIVIDER_MUXA2", ["DIVA", "REFCLK"]),
                          ("OUTDIVIDER_MUXB2", ["DIVB", "REFCLK"]),
                          ("OUTDIVIDER_MUXC2", ["DIVC", "REFCLK"]),
                          ("OUTDIVIDER_MUXD2", ["DIVD", "REFCLK"])]:
        for val in choices:
            targets.append(pll_target(
                f"{mux.lower()}_{val.lower()}",
                {mux: f'"{val}"'}))

    # PLL_LOCK_MODE (integer, not string; 0 or 1)
    for mode in [0, 1]:
        targets.append(pll_target(f"lock_mode{mode}", {"PLL_LOCK_MODE": mode}))

    return targets


def build_ebr_param_sweep() -> list[Target]:
    """EBR parameter sweep — mode, width, regmode, writemode, resetmode.

    prjtrellis 041-ebr_config equivalent.
    """
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    d0   = data_pin(bank, 1)
    ops  = out_pins(bank, 4)

    def dp8_target(name, extra_params=""):
        vlog = f"""\
    wire gnd = 1'b0;
    wire [7:0] doa_w;
    DP8KC #(
        .DATA_WIDTH_A(9), .DATA_WIDTH_B(9),
        .CSDECODE_A("0b111"), .CSDECODE_B("0b111"),
        .REGMODE_A("NOREG"), .REGMODE_B("NOREG"),
        .WRITEMODE_A("NORMAL"), .WRITEMODE_B("NORMAL"),
        .RESETMODE("SYNC"), .GSR("DISABLED"){extra_params}
    ) u0 (
        .CLKA(clk), .CEA(gnd), .OCEA(gnd), .WEA(gnd), .CSA2(gnd), .CSA1(gnd), .CSA0(gnd), .RSTA(gnd),
        .CLKB(clk), .CEB(gnd), .OCEB(gnd), .WEB(gnd), .CSB2(gnd), .CSB1(gnd), .CSB0(gnd), .RSTB(gnd),
        .ADA8(gnd), .ADA7(gnd), .ADA6(gnd), .ADA5(gnd), .ADA4(gnd),
        .ADA3(gnd), .ADA2(gnd), .ADA1(gnd), .ADA0(gnd),
        .ADB8(gnd), .ADB7(gnd), .ADB6(gnd), .ADB5(gnd), .ADB4(gnd),
        .ADB3(gnd), .ADB2(gnd), .ADB1(gnd), .ADB0(gnd),
        .DIA8(gnd), .DIA7(gnd), .DIA6(gnd), .DIA5(gnd), .DIA4(gnd),
        .DIA3(gnd), .DIA2(gnd), .DIA1(gnd), .DIA0(gnd),
        .DIB8(gnd), .DIB7(gnd), .DIB6(gnd), .DIB5(gnd), .DIB4(gnd),
        .DIB3(gnd), .DIB2(gnd), .DIB1(gnd), .DIB0(gnd),
        .DOA8(), .DOA7(doa_w[7]), .DOA6(doa_w[6]), .DOA5(doa_w[5]), .DOA4(doa_w[4]),
        .DOA3(doa_w[3]), .DOA2(doa_w[2]), .DOA1(doa_w[1]), .DOA0(doa_w[0]),
        .DOB8(), .DOB7(), .DOB6(), .DOB5(), .DOB4(),
        .DOB3(), .DOB2(), .DOB1(), .DOB0()
    );
    reg out0_r;
    always @(posedge clk) out0_r <= ^doa_w;
    assign out0 = out0_r;
"""
        return Target(
            name=f"ebr_dp8kc_{name}",
            verilog=verilog_module("    input wire clk,\n    output wire out0", vlog),
            bank=bank,
            lpf_pins=[lpf_pin_entry("clk", ck), lpf_pin_entry("out0", ops[0], "out")],
        )

    # DATA_WIDTH_A / B
    for w in ["1", "2", "4", "9"]:
        targets.append(dp8_target(f"dwa{w}", f',\n        .DATA_WIDTH_A({w})'))
        targets.append(dp8_target(f"dwb{w}", f',\n        .DATA_WIDTH_B({w})'))

    # REGMODE
    for rm in ["NOREG", "OUTREG"]:
        targets.append(dp8_target(f"regmode_{rm.lower()}", f',\n        .REGMODE_A("{rm}")'))

    # WRITEMODE
    for wm in ["WRITETHROUGH", "READBEFOREWRITE", "NORMAL"]:
        targets.append(dp8_target(f"wm_{_safe_name(wm).lower()}", f',\n        .WRITEMODE_A("{wm}")'))

    # RESETMODE
    for rsm in ["SYNC", "ASYNC"]:
        targets.append(dp8_target(f"rst_{rsm.lower()}", f',\n        .RESETMODE("{rsm}")'))

    # GSR
    for gsr in ["ENABLED", "DISABLED"]:
        targets.append(dp8_target(f"gsr_{gsr.lower()}", f',\n        .GSR("{gsr}")'))

    # PDPW8KC: write port is fixed-width (18 only); read port: 1,2,4,9,18
    for wr in ["1", "2", "4", "9", "18"]:
        for ww in ["18"]:
            vlog = f"""\
    wire gnd = 1'b0;
    wire [17:0] dout_w;
    PDPW8KC #(
        .DATA_WIDTH_R({wr}), .DATA_WIDTH_W({ww}),
        .CSDECODE_R("0b111"), .CSDECODE_W("0b111"),
        .GSR("DISABLED"), .RESETMODE("SYNC")
    ) u0 (
        .CLKW(clk), .CEW(gnd), .CSW2(gnd), .CSW1(gnd), .CSW0(gnd), .RST(gnd),
        .CLKR(clk), .CER(gnd), .OCER(gnd), .CSR2(gnd), .CSR1(gnd), .CSR0(gnd),
        .ADW8(gnd),.ADW7(gnd),.ADW6(gnd),.ADW5(gnd),.ADW4(gnd),.ADW3(gnd),.ADW2(gnd),.ADW1(gnd),.ADW0(gnd),
        .ADR10(gnd),.ADR9(gnd),.ADR8(gnd),.ADR7(gnd),.ADR6(gnd),.ADR5(gnd),.ADR4(gnd),.ADR3(gnd),.ADR2(gnd),.ADR1(gnd),.ADR0(gnd),
        .DI17(gnd),.DI16(gnd),.DI15(gnd),.DI14(gnd),.DI13(gnd),.DI12(gnd),.DI11(gnd),.DI10(gnd),
        .DI9(gnd),.DI8(gnd),.DI7(gnd),.DI6(gnd),.DI5(gnd),.DI4(gnd),.DI3(gnd),.DI2(gnd),.DI1(gnd),.DI0(gnd),
        .DO17(dout_w[17]),.DO16(dout_w[16]),.DO15(dout_w[15]),.DO14(dout_w[14]),
        .DO13(dout_w[13]),.DO12(dout_w[12]),.DO11(dout_w[11]),.DO10(dout_w[10]),
        .DO9(dout_w[9]),.DO8(dout_w[8]),.DO7(dout_w[7]),.DO6(dout_w[6]),
        .DO5(dout_w[5]),.DO4(dout_w[4]),.DO3(dout_w[3]),.DO2(dout_w[2]),.DO1(dout_w[1]),.DO0(dout_w[0])
    );
    reg out0_r;
    always @(posedge clk) out0_r <= ^dout_w;
    assign out0 = out0_r;
"""
            targets.append(Target(
                name=f"ebr_pdpw8kc_wr{wr}_ww{ww}",
                verilog=verilog_module("    input wire clk,\n    output wire out0", vlog),
                bank=bank,
                lpf_pins=[lpf_pin_entry("clk", ck), lpf_pin_entry("out0", ops[0], "out")],
            ))

    return targets


def build_clkdiv_sweep() -> list[Target]:
    """CLKDIVC DIVISOR sweep — all 4 values."""
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    op   = out_pins(bank, 1)[0]
    for divisor in ["2.0", "3.5", "4.0"]:
        div_safe = _safe_name(divisor)
        vlog = f"""\
    wire gnd = 1'b0;
    wire cdivx_w;
    CLKDIVC #(.DIV("{divisor}"), .GSR("ENABLED")) u0 (
        .CLKI(clk), .RST(gnd), .ALIGNWD(gnd), .CDIV1(), .CDIVX(cdivx_w)
    );
    reg out0_r;
    always @(posedge cdivx_w) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
        targets.append(Target(
            name=f"clkdivc_div{div_safe}",
            verilog=verilog_module("    input wire clk,\n    output wire out0", vlog),
            bank=bank,
            lpf_pins=[lpf_pin_entry("clk", ck), lpf_pin_entry("out0", op, "out")],
        ))
    return targets


def build_eclksync_sweep() -> list[Target]:
    """ECLKSYNCA attribute sweep — STOP value (0/1)."""
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    op   = out_pins(bank, 1)[0]
    for stop in ["0", "1"]:
        vlog = f"""\
    wire gnd = 1'b0;
    wire ecsout_w;
    ECLKSYNCA u0 (.ECLKI(clk), .STOP(1'b{stop}), .ECLKO(ecsout_w));
    reg out0_r;
    always @(posedge ecsout_w) out0_r <= ~out0_r;
    assign out0 = out0_r;
"""
        targets.append(Target(
            name=f"eclksynca_stop{stop}",
            verilog=verilog_module("    input wire clk,\n    output wire out0", vlog),
            bank=bank,
            lpf_pins=[lpf_pin_entry("clk", ck), lpf_pin_entry("out0", op, "out")],
        ))
    return targets


def build_delay_sweep() -> list[Target]:
    """Input delay sweep — DEL_VALUE attribute on IB (0-31, 5-bit field).

    prjtrellis 066-iodelay sweeps IOLOGIC.DELAY.DEL_VALUE as a 5-bit word (0–31).
    In Diamond Verilog the equivalent is the (* DEL_VALUE=n *) attribute on IB/BB.
    Note: DELAYE/DELAYD primitives cannot be instantiated standalone (their output
    only routes to IOLOGIC, not fabric) — DEL_VALUE attribute is the correct approach.
    """
    targets = []
    for bank in [0, 1, 2]:
        ck  = clk_pin(bank)
        d0  = data_pin(bank, 1)
        op  = out_pins(bank, 1)[0]
        pin = d0
        for step in range(32):
            vlog = f"""\
    wire q_w;
    (* LOC="{pin}", IO_TYPE="LVCMOS33", DEL_VALUE={step} *)
    IB u0 (.I(d), .O(q_w));
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
            targets.append(Target(
                name=f"ib_del{step:02d}_bank{bank}",
                verilog=verilog_module(
                    "    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    pin),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))
    return targets


def build_iologic_mode_sweep() -> list[Target]:
    """IOLOGIC mode sweep — IFS1P3xX / OFS1P3xX variants per bank.

    Sweeps the clock-enable and set/reset variants of the IO FFs
    to capture the mode bits in the IOLOGIC tile.
    """
    targets = []

    # IFS1P3BX: posedge, async clr, CE
    # IFS1P3DX: posedge, async clr, no CE
    # IFS1P3IX: posedge, async set (via SCLK?)
    # IFS1P3JX: negedge, async clr
    # IFS1S1B / IFS1S1D / IFS1S1I / IFS1S1J: single-data variants

    for bank in [0, 1, 2]:
        ck  = clk_pin(bank)
        d0  = data_pin(bank, 1)
        op  = out_pins(bank, 1)[0]

        # IFS1P3*: input IO FF — Q goes to fabric reg then output pad
        # SP=enable, SCLK=clock, CD=async clear, PD=async preset
        for prim, prim_desc, rst_port in [
            ("IFS1P3BX", "ifs1p3bx", ".PD(1'b0)"),
            ("IFS1P3DX", "ifs1p3dx", ".CD(1'b0)"),
            ("IFS1P3IX", "ifs1p3ix", ".CD(1'b0)"),
            ("IFS1P3JX", "ifs1p3jx", ".PD(1'b0)"),
        ]:
            vlog = f"""\
    wire q_w;
    {prim} u0 (.D(d), .SP(1'b1), .SCLK(clk), {rst_port}, .Q(q_w));
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
            targets.append(Target(
                name=f"{prim_desc}_bank{bank}",
                verilog=verilog_module(
                    "    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    d0),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))

        # OFS1P3*: output IO FF — Q drives the output pad directly (no fabric FF)
        for prim, prim_desc, rst_port in [
            ("OFS1P3BX", "ofs1p3bx", ".PD(1'b0)"),
            ("OFS1P3DX", "ofs1p3dx", ".CD(1'b0)"),
            ("OFS1P3IX", "ofs1p3ix", ".CD(1'b0)"),
            ("OFS1P3JX", "ofs1p3jx", ".PD(1'b0)"),
        ]:
            vlog = f"""\
    wire gnd = 1'b0;
    reg d_r;
    always @(posedge clk) d_r <= d;
    {prim} u0 (.D(d_r), .SP(1'b1), .SCLK(clk), {rst_port}, .Q(out0));
"""
            targets.append(Target(
                name=f"{prim_desc}_bank{bank}",
                verilog=verilog_module(
                    "    input wire clk,\n    input wire d,\n    output wire out0",
                    vlog),
                bank=bank,
                lpf_pins=[
                    lpf_pin_entry("clk",  ck),
                    lpf_pin_entry("d",    d0),
                    lpf_pin_entry("out0", op, "out"),
                ],
            ))

    return targets


def build_tsall_sweep() -> list[Target]:
    """TSALL instantiation — driven low (outputs enabled) vs high (all tristated).

    TSALL port name is 'TSALL', not 'TSALLI'. Diamond Diamond: module TSALL(TSALL).
    We just instantiate it with a constant to capture the bitstream footprint.
    """
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    d0   = data_pin(bank, 1)
    op   = out_pins(bank, 1)[0]
    for tsval in ["0", "1"]:
        vlog = f"""\
    wire q_w;
    TSALL u0 (.TSALL(1'b{tsval}));
    reg out0_r;
    always @(posedge clk) out0_r <= d;
    assign out0 = out0_r;
"""
        targets.append(Target(
            name=f"tsall_const{tsval}",
            verilog=verilog_module(
                "    input wire clk,\n    input wire d,\n    output wire out0",
                vlog),
            bank=bank,
            lpf_pins=[
                lpf_pin_entry("clk",  ck),
                lpf_pin_entry("d",    d0),
                lpf_pin_entry("out0", op, "out"),
            ],
        ))
    return targets


def build_dlldelc_sweep() -> list[Target]:
    """DLLDELC DEL_ADJ / DEL_VAL sweep — SKIPPED.

    DLLDELC requires placement in a DLL-capable site with specific ECLK routing.
    Diamond PAR rejects standalone placement outside a DLL IO group.
    prjtrellis 132-dlldel uses NCL structural placement that bypasses this check.
    Cannot be reproduced via Verilog + LPF pin constraints alone.
    """
    return []


def build_pll_os_sweep() -> list[Target]:
    """EHXPLLJ CLKOS/OS2/OS3 CPHASE, FPHASE, DIV full sweeps.

    prjtrellis sweeps CPHASE(0-127) and FPHASE(0-7) for each output clock.
    We do CLKOS, CLKOS2, CLKOS3 independently.
    """
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    op   = out_pins(bank, 1)[0]

    def pll_os_target(name: str, extra_params: str, enclk: str = "ENCLKOS") -> Target:
        vlog = f"""\
    wire gnd = 1'b0;
    wire vcc = 1'b1;
    wire clkop_w, clkos_w, clkos2_w, clkos3_w, lock_w;
    EHXPLLJ #(
        .CLKI_DIV(1), .CLKFB_DIV(1), .CLKOP_DIV(1),
        .CLKOP_ENABLE("ENABLED"), .CLKOS_ENABLE("ENABLED"),
        .CLKOS2_ENABLE("ENABLED"), .CLKOS3_ENABLE("ENABLED"),
        .FEEDBK_PATH("INT_DIVA"){extra_params}
    ) u0 (
        .CLKI(clk), .CLKFB(gnd), .RST(gnd), .STDBY(gnd), .PLLWAKESYNC(gnd),
        .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd), .PHASESTEP(gnd), .LOADREG(gnd),
        .RESETM(gnd), .RESETC(gnd), .RESETD(gnd),
        .ENCLKOP(vcc), .ENCLKOS(vcc), .ENCLKOS2(vcc), .ENCLKOS3(vcc),
        .PLLCLK(gnd), .PLLRST(gnd), .PLLSTB(gnd), .PLLWE(gnd),
        .PLLADDR4(gnd), .PLLADDR3(gnd), .PLLADDR2(gnd), .PLLADDR1(gnd), .PLLADDR0(gnd),
        .PLLDATI7(gnd), .PLLDATI6(gnd), .PLLDATI5(gnd), .PLLDATI4(gnd),
        .PLLDATI3(gnd), .PLLDATI2(gnd), .PLLDATI1(gnd), .PLLDATI0(gnd),
        .CLKOP(clkop_w), .CLKOS(clkos_w), .CLKOS2(clkos2_w), .CLKOS3(clkos3_w), .LOCK(lock_w)
    );
    reg out0_r;
    always @(posedge clkop_w) out0_r <= lock_w;
    assign out0 = out0_r;
"""
        return Target(
            name=f"pll_{name}",
            verilog=verilog_module("    input wire clk,\n    output wire out0", vlog),
            bank=bank,
            lpf_pins=[lpf_pin_entry("clk", ck), lpf_pin_entry("out0", op, "out")],
        )

    # CLKOS2/OS3 DIV sweeps skipped — same Diamond phase-shift DRC as CLKOP_DIV.
    # Only DIV=1 on all outputs passes standalone without a full SDC timing flow.

    # CPHASE and FPHASE sweeps for OS/OS2/OS3 skipped — same Diamond DRC as CLKOP:
    # any non-zero phase shift on any output clock is rejected standalone without SDC.

    # FRACN_DIV (16-bit) — do every 64th value (1024 samples covers full range)
    for v in range(0, 65536, 64):
        targets.append(pll_os_target(f"fracn_div{v:05d}",
                                     f', .FRACN_ENABLE("ENABLED"), .FRACN_DIV({v})'))

    # PREDIVIDER_MUX (0-3 each)
    for mux in ["MUXA1", "MUXB1", "MUXC1", "MUXD1"]:
        for v in range(4):
            targets.append(pll_os_target(f"prediv_{mux.lower()}_v{v}",
                                         f", .PREDIVIDER_{mux}({v})"))

    # PLL_LOCK_MODE (0 and 1 are the documented values)
    for v in [0, 1]:
        targets.append(pll_os_target(f"pll_lock_mode{v}", f", .PLL_LOCK_MODE({v})"))

    return targets


def build_ebr_numeric_sweep() -> list[Target]:
    """EBR numeric parameter sweep — CSDECODE (3-bit) and ASYNC_RESET_RELEASE.

    prjtrellis sweeps CSDECODE_A/B (0-7) and ASYNC_RESET_RELEASE (SYNC/ASYNC).
    WID is an NCL-internal tag, not a Verilog DP8KC parameter — excluded.
    """
    targets = []
    bank = 0
    ck   = clk_pin(bank)
    op   = out_pins(bank, 1)[0]

    def dp8_target(name: str, csdec_a: str, csdec_b: str, arr: str) -> Target:
        vlog = f"""\
    wire gnd = 1'b0;
    wire [7:0] doa_w;
    DP8KC #(
        .DATA_WIDTH_A(9), .DATA_WIDTH_B(9),
        .CSDECODE_A("{csdec_a}"), .CSDECODE_B("{csdec_b}"),
        .REGMODE_A("NOREG"), .REGMODE_B("NOREG"),
        .WRITEMODE_A("NORMAL"), .WRITEMODE_B("NORMAL"),
        .RESETMODE("SYNC"), .GSR("DISABLED"),
        .ASYNC_RESET_RELEASE("{arr}")
    ) u0 (
        .CLKA(clk), .CEA(gnd), .OCEA(gnd), .WEA(gnd), .CSA2(gnd), .CSA1(gnd), .CSA0(gnd), .RSTA(gnd),
        .CLKB(clk), .CEB(gnd), .OCEB(gnd), .WEB(gnd), .CSB2(gnd), .CSB1(gnd), .CSB0(gnd), .RSTB(gnd),
        .ADA8(gnd),.ADA7(gnd),.ADA6(gnd),.ADA5(gnd),.ADA4(gnd),.ADA3(gnd),.ADA2(gnd),.ADA1(gnd),.ADA0(gnd),
        .ADB8(gnd),.ADB7(gnd),.ADB6(gnd),.ADB5(gnd),.ADB4(gnd),.ADB3(gnd),.ADB2(gnd),.ADB1(gnd),.ADB0(gnd),
        .DIA8(gnd),.DIA7(gnd),.DIA6(gnd),.DIA5(gnd),.DIA4(gnd),.DIA3(gnd),.DIA2(gnd),.DIA1(gnd),.DIA0(gnd),
        .DIB8(gnd),.DIB7(gnd),.DIB6(gnd),.DIB5(gnd),.DIB4(gnd),.DIB3(gnd),.DIB2(gnd),.DIB1(gnd),.DIB0(gnd),
        .DOA8(),.DOA7(doa_w[7]),.DOA6(doa_w[6]),.DOA5(doa_w[5]),.DOA4(doa_w[4]),
        .DOA3(doa_w[3]),.DOA2(doa_w[2]),.DOA1(doa_w[1]),.DOA0(doa_w[0]),
        .DOB8(),.DOB7(),.DOB6(),.DOB5(),.DOB4(),.DOB3(),.DOB2(),.DOB1(),.DOB0()
    );
    reg out0_r;
    always @(posedge clk) out0_r <= ^doa_w;
    assign out0 = out0_r;
"""
        return Target(
            name=name,
            verilog=verilog_module("    input wire clk,\n    output wire out0", vlog),
            bank=bank,
            lpf_pins=[lpf_pin_entry("clk", ck), lpf_pin_entry("out0", op, "out")],
        )

    # CSDECODE_A (0-7), B fixed at 0b000
    for v in range(8):
        targets.append(dp8_target(f"ebr_dp8kc_csdec_a{v}", f"0b{v:03b}", "0b000", "SYNC"))

    # CSDECODE_B (0-7), A fixed at 0b000
    for v in range(8):
        targets.append(dp8_target(f"ebr_dp8kc_csdec_b{v}", "0b000", f"0b{v:03b}", "SYNC"))

    # ASYNC_RESET_RELEASE
    for arr in ["SYNC", "ASYNC"]:
        targets.append(dp8_target(f"ebr_dp8kc_arr_{arr.lower()}", "0b000", "0b000", arr))

    return targets


def build_bb_attr_sweep() -> list[Target]:
    """BB tristate-enable attribute sweep — T driven low vs high per bank.

    The bidir pad (bio) is a separate inout port; out0 is a registered output
    carrying the loopback read value from BB.O.
    """
    targets = []
    for bank in [0, 1, 2]:
        ck  = clk_pin(bank)
        d0  = data_pin(bank, 1)
        bp  = data_pin(bank, 2)   # bidir pad pin
        op  = out_pins(bank, 1)[0]

        # BB with tristate driven low (output always enabled)
        vlog = f"""\
    wire gnd = 1'b0;
    wire q_w;
    (* LOC="{bp}", IO_TYPE="LVCMOS33" *)
    BB u0 (.B(bio), .I(d), .T(gnd), .O(q_w));
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
        targets.append(Target(
            name=f"bb_ts_low_bank{bank}",
            verilog=verilog_module(
                "    input wire clk,\n    input wire d,\n    inout wire bio,\n    output wire out0",
                vlog),
            bank=bank,
            lpf_pins=[
                lpf_pin_entry("clk",  ck),
                lpf_pin_entry("d",    d0),
                lpf_pin_entry("bio",  bp, "bidir"),
                lpf_pin_entry("out0", op, "out"),
            ],
        ))

        # BB with tristate driven high (output tristated)
        vlog = f"""\
    wire vcc = 1'b1;
    wire q_w;
    (* LOC="{bp}", IO_TYPE="LVCMOS33" *)
    BB u0 (.B(bio), .I(d), .T(vcc), .O(q_w));
    reg out0_r;
    always @(posedge clk) out0_r <= q_w;
    assign out0 = out0_r;
"""
        targets.append(Target(
            name=f"bb_ts_high_bank{bank}",
            verilog=verilog_module(
                "    input wire clk,\n    input wire d,\n    inout wire bio,\n    output wire out0",
                vlog),
            bank=bank,
            lpf_pins=[
                lpf_pin_entry("clk",  ck),
                lpf_pin_entry("d",    d0),
                lpf_pin_entry("bio",  bp, "bidir"),
                lpf_pin_entry("out0", op, "out"),
            ],
        ))

    return targets


# ---------------------------------------------------------------------------
# Master target list
# ---------------------------------------------------------------------------

def all_targets() -> list[Target]:
    return (
        build_ddr_iologic_targets()
        + build_io_ff_targets()
        + build_delay_targets()
        + build_io_buffer_targets()
        + build_clock_targets()
        + build_pll_targets()
        + build_osch_targets()
        + build_ebr_targets()
        + build_rom_targets()
        + build_efb_targets()
        + build_jtag_targets()
        + build_hardblock_targets()
        + build_ccu2d_targets()
        + build_highlevel_targets()
        + build_pio_attr_sweep()
        + build_lut_ff_sweep()
        + build_osch_freq_sweep()
        + build_gsr_sweep()
        + build_sed_sweep()
        + build_pcntr_sweep()
        + build_sysconfig_sweep()
        + build_pll_param_sweep()
        + build_ebr_param_sweep()
        + build_clkdiv_sweep()
        + build_eclksync_sweep()
        + build_delay_sweep()
        + build_iologic_mode_sweep()
        + build_bb_attr_sweep()
        + build_tsall_sweep()
        + build_dlldelc_sweep()
        + build_pll_os_sweep()
        + build_ebr_numeric_sweep()
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def write_target(target: Target, base: Path, dry_run: bool = False) -> Path:
    dest = target.dir_path(base)
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "fuzz.v").write_text(target.verilog)
        (dest / "fuzz.lpf").write_text(make_lpf(target))
        (dest / "run.tcl").write_text(TCL_TEMPLATE)
        (dest / "fuzz.ldf").write_text(make_ldf())
    return dest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets-dir", type=Path, default=TARGETS_DIR,
                        help="Root directory for generated targets (default: fuzz/targets/)")
    parser.add_argument("--list", action="store_true",
                        help="List all target names and exit (no files written)")
    parser.add_argument("--only", metavar="NAME",
                        help="Generate only the named target (substring match)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written without writing files")
    args = parser.parse_args()

    targets = all_targets()

    if args.list:
        for t in targets:
            print(t.name)
        print(f"\n{len(targets)} targets total")
        return

    if args.only:
        targets = [t for t in targets if args.only in t.name]
        if not targets:
            print(f"ERROR: no targets match '{args.only}'")
            return

    base = args.targets_dir
    if not args.dry_run:
        base.mkdir(parents=True, exist_ok=True)

    written = 0
    for t in targets:
        dest = write_target(t, base, dry_run=args.dry_run)
        if args.dry_run:
            print(f"[dry] {dest}")
        else:
            print(f"  {dest.relative_to(base.parent)}")
        written += 1

    print(f"\n{'[dry] ' if args.dry_run else ''}{written} targets {'listed' if args.dry_run else 'written'} under {base}")


if __name__ == "__main__":
    main()
