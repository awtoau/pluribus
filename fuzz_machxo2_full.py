#!/usr/bin/env python3
"""fuzz_machxo2_full.py — comprehensive MachXO2 LCMXO2-1200 TQFP100 routing fuzzer.

Covers every synthesisable primitive type: pads, LUTs, FFs, carry chains,
distributed RAM (DPRAM/RAMW), block RAM (EBR DP8KC), PLL (EHXPLLJ), IOLOGIC
(IDDR/ODDR), EFB (WB/SPI/I2C/Timer/UFM), and long-line/global wires.

All results go into Postgres (fpga_re DB) with a unified schema queryable via SQL.
Fully resumable — kill and restart at any point.

Primary target: LCMXO2-1200 TQFP100 (our device).
Secondary: all other LCMXO2 devices/packages (--all-devices flag).

Usage:
    python3 fpga/scripts/fuzz_machxo2_full.py              # LCMXO2-1200 TQFP100
    python3 fpga/scripts/fuzz_machxo2_full.py --all-devices
    python3 fpga/scripts/fuzz_machxo2_full.py --report
    python3 fpga/scripts/fuzz_machxo2_full.py --kill

DB:  fpga_re (Postgres) — connection via PLURIBUS_DSN env var or default dbname=fpga_re
Log: fpga/tmp/fuzz_full.log

Upstream contribution: prjcombine MachXO2 routing database (issue #76).
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import psycopg2
from psycopg2 import extras as _pgextras

# ---------------------------------------------------------------------------
# Paths / toolchain
# ---------------------------------------------------------------------------
_HERE   = Path(__file__).parent
_ROOT   = _HERE.parent.parent
_LOG    = _ROOT / "fpga" / "tmp" / "fuzz_full.log"

_TRELLIS_BUILD  = os.environ.get("TRELLIS_BUILD",
    str(_ROOT / "debris/tmp/prjtrellis/libtrellis/build"))
_TRELLIS_DBROOT = os.environ.get("TRELLIS_DBROOT",
    str(_ROOT / "debris/tmp/prjtrellis/database"))


import shutil as _shutil
_NEXTPNR_BIN = (os.environ.get("NEXTPNR_MACHXO2")
                or _shutil.which("nextpnr-machxo2")
                or "/home/dan/opt/oss-cad-suite/bin/nextpnr-machxo2")

sys.path.insert(0, str(_HERE))
os.environ["TRELLIS_BUILD"]  = _TRELLIS_BUILD
os.environ["TRELLIS_DBROOT"] = _TRELLIS_DBROOT
import machxo2_lift as mx

# ---------------------------------------------------------------------------
# Device / package matrix
# ---------------------------------------------------------------------------
PRIMARY_DEVICE  = "LCMXO2-1200"
PRIMARY_PACKAGE = "TQFP100"

ALL_DEVICES = [
    "LCMXO2-256", "LCMXO2-640", "LCMXO2-1200",
    "LCMXO2-2000", "LCMXO2-4000", "LCMXO2-7000",
]

# nextpnr device name (with speed grade) from device + package
def nextpnr_device(device: str, package: str) -> str:
    pkg = (package.replace("TQFP", "TG").replace("QFN", "QN")
                  .replace("CSBGA", "BG").replace("WLCSP", "WL")
                  .replace("CABGA", "BG").replace("FTBGA", "FT")
                  .replace("FPBGA", "FP").replace("UCBGA", "BG"))
    return f"{device}HC-4{pkg}C"

# Dedicated clock pin per device (used for FF/EBR/PLL designs that need a clock)
_CLK_PIN = {
    "LCMXO2-1200": {"TQFP100": "95", "TQFP144": "112", "CSBGA132": "95",
                    "QFN32": "28", "WLCSP25": "E3", "WLCSP36": "E4"},
}
_DEFAULT_CLK_PIN = "1"

def clk_pin_for(device: str, package: str) -> str:
    return _CLK_PIN.get(device, {}).get(package, _DEFAULT_CLK_PIN)

# ---------------------------------------------------------------------------
# DB helpers (Postgres — per-thread connection via threading.local)
# ---------------------------------------------------------------------------
_tls = threading.local()

def _conn():
    """Return a per-thread psycopg2 connection to fpga_re."""
    if not getattr(_tls, 'con', None):
        dsn = os.environ.get('PLURIBUS_DSN', 'dbname=fpga_re')
        _tls.con = psycopg2.connect(dsn)
        _tls.con.autocommit = False
    return _tls.con

def _tool_ver(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        return out.splitlines()[0] if out else "unknown"
    except Exception as e:
        return f"error:{e}"

def capture_toolchain():
    yv = _tool_ver(["yowasp-yosys", "--version"])
    nv = _tool_ver([_NEXTPNR_BIN, "--version"])
    ts = _now()
    con = _conn()
    con.cursor().execute(
        "INSERT INTO fuzz_toolchain_versions(yosys_version,nextpnr_version,recorded_at)"
        " VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
        (yv, nv, ts)
    )
    con.commit()
    return yv, nv

def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")

def run_exists(device, package, pclass, pvariant, site_tag) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "SELECT id FROM fuzz_runs WHERE device=%s AND package=%s AND primitive_class=%s "
        "AND primitive_variant=%s AND site_tag=%s AND status!='pending'",
        (device, package, pclass, pvariant, site_tag)
    )
    return cur.fetchone() is not None

def insert_run(device, package, pclass, pvariant, site_tag,
               tile_row=None, tile_col=None, design_params=None) -> int:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO fuzz_runs(device,package,primitive_class,primitive_variant,"
        "site_tag,tile_row,tile_col,status,run_at,design_params) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s) ON CONFLICT DO NOTHING RETURNING id",
        (device, package, pclass, pvariant, site_tag, tile_row, tile_col, _now(), design_params)
    )
    row = cur.fetchone()
    con.commit()
    if row:
        return row[0]
    cur.execute(
        "SELECT id FROM fuzz_runs WHERE device=%s AND package=%s AND primitive_class=%s "
        "AND primitive_variant=%s AND site_tag=%s",
        (device, package, pclass, pvariant, site_tag)
    )
    return cur.fetchone()[0]

def update_run(run_id, status, bshash=None, error=None,
               yv=None, nv=None, rtl_hash=None):
    con = _conn()
    con.cursor().execute(
        "UPDATE fuzz_runs SET status=%s,bitstream_hash=%s,error_msg=%s,"
        "yosys_version=%s,nextpnr_version=%s,rtl_hash=%s WHERE id=%s",
        (status, bshash, error, yv, nv, rtl_hash, run_id)
    )
    con.commit()

def insert_wires(run_id, wires):
    con = _conn()
    _pgextras.execute_values(
        con.cursor(),
        "INSERT INTO fuzz_wires(run_id,tile_row,tile_col,wire_name,is_sink,"
        "globalise_ok,global_x,global_y,global_id) VALUES %s",
        [(run_id, r, c, name, is_sink, ok, gx, gy, gid)
         for (r, c, name, is_sink, ok, gx, gy, gid) in wires]
    )
    con.commit()

def insert_log(run_id, stage, stdout, stderr):
    con = _conn()
    con.cursor().execute(
        "INSERT INTO synth_logs(run_id,stage,stdout,stderr) VALUES(%s,%s,%s,%s)",
        (run_id, stage, stdout[:8000], stderr[:8000])
    )
    con.commit()

# ---------------------------------------------------------------------------
# Wire extraction (shared by all primitive types)
# ---------------------------------------------------------------------------
def extract_wires_from_config(device, cfg_path, lift=None):
    """Parse a .config file and extract all arc wires with globalise results.
    Returns list of (tile_row, tile_col, wire_name, is_sink, ok, gx, gy, gid)."""
    if lift is None:
        lift = mx.MachXO2Lift(device)
    pc = lift.parse_config(cfg_path)
    rows = []
    seen = set()
    for (r, c, sink, source) in pc.arcs:
        for name, is_sink in ((sink, True), (source, False)):
            key = (r, c, name, is_sink)
            if key in seen:
                continue
            seen.add(key)
            g = lift.rg.globalise_net(r, c, name)
            ok = (g.loc.x >= 0 and g.loc.y >= 0)
            rows.append((r, c, name, is_sink,
                         ok, g.loc.x if ok else None, g.loc.y if ok else None,
                         g.id if ok else None))
    return rows

# ---------------------------------------------------------------------------
# Black-box stub library for primitives yowasp-yosys doesn't know natively
# ---------------------------------------------------------------------------
_BLACKBOX_LIB = """\
(* blackbox *)
module EFB #(
  parameter EFB_WB   = "DISABLED",
  parameter EFB_SPI  = "DISABLED",
  parameter EFB_I2C1 = "DISABLED",
  parameter EFB_I2C2 = "DISABLED",
  parameter EFB_TC   = "DISABLED"
)(
  input  WBCLKI, WBSTBI, WBCYCI, WBWEI,
  input  WBADRI7, WBADRI6, WBADRI5, WBADRI4,
  input  WBADRI3, WBADRI2, WBADRI1, WBADRI0,
  input  WBDATI7, WBDATI6, WBDATI5, WBDATI4,
  input  WBDATI3, WBDATI2, WBDATI1, WBDATI0,
  output WBDATO7, WBDATO6, WBDATO5, WBDATO4,
  output WBDATO3, WBDATO2, WBDATO1, WBDATO0,
  output WBACKO,
  output SPIIRQO, SPIMISOO, SPIMOSIO, SPISCKO,
  input  SPIMCSN0, SPIMCSN1, SPIMCSN2, SPIMCSN3,
  input  SPIMCSN4, SPIMCSN5, SPIMCSN6, SPIMCSN7,
  output TCOC, TCINT, UFMSN,
  output I2C1IRQO, I2C2IRQO
); endmodule

(* blackbox *)
module IDDRX1F(
  input D, input SCLK, input RST,
  output Q0, output Q1
); endmodule

(* blackbox *)
module ODDRX1F(
  input D0, input D1, input SCLK,
  output Q
); endmodule
"""

# ---------------------------------------------------------------------------
# Synthesis helper
# ---------------------------------------------------------------------------
def synthesise(device, package, verilog, lpf, tmpdir, run_id,
               yv=None, nv=None):
    """Run yosys+nextpnr. Returns ('ok', cfg_path, bshash) or ('STATUS', None, None)."""
    v_f    = tmpdir / "design.v"
    bb_f   = tmpdir / "blackbox.v"
    json_f = tmpdir / "design.json"
    lpf_f  = tmpdir / "design.lpf"
    cfg_f  = tmpdir / "design.config"

    v_f.write_text(verilog)
    bb_f.write_text(_BLACKBOX_LIB)
    lpf_f.write_text(lpf)

    rtl_hash = hashlib.sha256(verilog.encode()).hexdigest()[:16]

    r = subprocess.run(
        ["yowasp-yosys", "-p",
         f"read_verilog -lib {bb_f}; read_verilog {v_f}; synth_lattice -family xo2 -json {json_f}"],
        capture_output=True, text=True
    )
    insert_log(run_id, "yosys", r.stdout, r.stderr)
    if r.returncode != 0:
        update_run(run_id, "synth_fail", error=r.stderr[-500:], yv=yv, nv=nv,
                   rtl_hash=rtl_hash)
        return "synth_fail", None, None

    ndev = nextpnr_device(device, package)
    r2 = subprocess.run(
        [_NEXTPNR_BIN, "--device", ndev, "--json", str(json_f),
         "--lpf", str(lpf_f), "--lpf-allow-unconstrained",
         "--textcfg", str(cfg_f), "--force"],
        capture_output=True, text=True
    )
    insert_log(run_id, "nextpnr", r2.stdout, r2.stderr)
    if r2.returncode != 0 or not cfg_f.exists():
        update_run(run_id, "pnr_fail", error=r2.stderr[-500:], yv=yv, nv=nv,
                   rtl_hash=rtl_hash)
        return "pnr_fail", None, None

    bshash = hashlib.sha256(cfg_f.read_bytes()).hexdigest()[:16]
    update_run(run_id, "ok", bshash=bshash, yv=yv, nv=nv, rtl_hash=rtl_hash)
    return "ok", str(cfg_f), bshash

# ---------------------------------------------------------------------------
# Primitive class: PAD (input/output/bidir/ff_d/ff_q/ff_edge_hop)
# Same coverage as original fuzzer — included here for unified DB.
# ---------------------------------------------------------------------------
_PAD_PRIMITIVES = ["input", "output", "inout", "ff_d", "ff_q", "ff_edge_hop"]

def _pad_verilog(pin, primitive, clk_pin=None):
    p = f"p{pin}"
    if primitive == "input":
        return f"module top(input {p}, output out); assign out = {p}; endmodule\n"
    elif primitive in ("output", "inout"):
        return f"module top(input inp, output {p}); assign {p} = inp; endmodule\n"
    elif primitive == "ff_d":
        return (f"module top(input {p}, input clk, output reg q);\n"
                f"  always @(posedge clk) q <= {p};\nendmodule\n")
    elif primitive == "ff_q":
        return (f"module top(input d, input clk, output reg {p});\n"
                f"  always @(posedge clk) {p} <= d;\nendmodule\n")
    elif primitive == "ff_edge_hop":
        return (f"module top(input {p}, input clk, output reg q_out);\n"
                f"  reg stage1;\n"
                f"  always @(posedge clk) stage1 <= {p};\n"
                f"  always @(posedge clk) q_out <= stage1;\n"
                f"endmodule\n")
    return _pad_verilog(pin, "input")

def _pad_lpf(pin, primitive, clk_pin, ff_col=None, tile_row=None):
    p = f"p{pin}"
    lines = [f'LOCATE COMP "{p}" SITE "{pin}";',
             f'IOBUF PORT "{p}" IO_TYPE=LVTTL33;']
    if primitive in ("ff_d", "ff_q", "ff_edge_hop"):
        lines += [f'LOCATE COMP "clk" SITE "{clk_pin}";',
                  f'IOBUF PORT "clk" IO_TYPE=LVTTL33;']
    if primitive == "ff_edge_hop" and ff_col is not None and tile_row is not None:
        lines.append(f'LOCATE COMP "stage1" SITE "R{tile_row}C{ff_col}_SLICEA";')
    return "\n".join(lines)

def fuzz_pads(device, package, yv, nv, L, lift):
    iodb = mx.load_iodb(device)
    pkg_map = iodb["packages"].get(package, {})
    if not pkg_map:
        L(f"  SKIP {device}/{package}: no sites")
        return

    all_cols = [s["col"] for s in pkg_map.values()]
    max_col  = max(all_cols)

    site_list = sorted(set(
        (s["row"], s["col"], s["pio"]) for s in pkg_map.values()
    ))

    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)

    for (tile_row, tile_col, pio) in site_list:
        pkg_pin = next(
            (pin for pin, s in pkg_map.items()
             if s["row"] == tile_row and s["col"] == tile_col and s["pio"] == pio),
            None
        )
        if pkg_pin is None:
            continue

        for prim in _PAD_PRIMITIVES:
            if prim == "ff_edge_hop" and (tile_col < max_col - 1 or tile_col < 2):
                continue  # only right-edge pads

            site_tag = f"R{tile_row}C{tile_col}_{pio}"
            pclass   = "pad"

            if run_exists(device, package, pclass, prim, site_tag):
                continue

            run_id = insert_run(device, package, pclass, prim, site_tag,
                                tile_row, tile_col)

            clk = clk_pin_for(device, package)
            if clk == pkg_pin:
                clk = "1" if pkg_pin != "1" else "2"

            ff_col = tile_col - 1 if prim == "ff_edge_hop" else None
            verilog = _pad_verilog(pkg_pin, prim, clk)
            lpf     = _pad_lpf(pkg_pin, prim, clk, ff_col, tile_row)

            L(f"  PAD {device}/{package} R{tile_row}C{tile_col} {pio} {prim}")

            with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
                status, cfg, _ = synthesise(device, package, verilog, lpf,
                                            Path(td), run_id, yv, nv)
                if status == "ok":
                    try:
                        wires = extract_wires_from_config(device, cfg, lift)
                        insert_wires(run_id, wires)
                        L(f"    ok wires={len(wires)}")
                    except Exception as e:
                        update_run(run_id, "extract_fail", error=str(e)[:500])
                        L(f"    extract_fail: {e}")

# ---------------------------------------------------------------------------
# Primitive class: LUT
# One run per fabric tile (PLC tiles), varying LUT init and input count.
# Exercises: JA/JB/JC/JD input arcs, JF output arcs, local switchbox.
# ---------------------------------------------------------------------------
def _lut_verilog(n_inputs):
    """LUT with n_inputs — let nextpnr place freely, just constrain the clock pad."""
    inputs  = " ".join(f"input d{i}," for i in range(n_inputs))
    xor_str = " ^ ".join(f"d{i}" for i in range(n_inputs))
    return (
        f"module top(input clk, {inputs} output reg q);\n"
        f"  wire lut_out = {xor_str};\n"
        f"  always @(posedge clk) q <= lut_out;\n"
        f"endmodule\n"
    )

def _lut_lpf(clk_pin):
    # Free placement — only constrain the clock pad so synthesis is deterministic
    return (f'LOCATE COMP "clk" SITE "{clk_pin}";\n'
            f'IOBUF PORT "clk" IO_TYPE=LVTTL33;\n')

def fuzz_luts(device, package, yv, nv, L, lift):
    """Fuzz LUT routing at every fabric (PLC) tile."""
    chip = lift.chip
    clk  = clk_pin_for(device, package)
    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)

    for tile in chip.get_all_tiles():
        if tile.info.type != "PLC":
            continue
        tile_row = tile.row
        tile_col = tile.col

        for n in (2, 4):
            pvariant = f"lut{n}"
            site_tag = f"R{tile_row}C{tile_col}"

            if run_exists(device, package, "lut", pvariant, site_tag):
                continue

            run_id = insert_run(device, package, "lut", pvariant, site_tag,
                                tile_row, tile_col)
            verilog = _lut_verilog(n)
            lpf     = _lut_lpf(clk)

            L(f"  LUT{n} {device}/{package} R{tile_row}C{tile_col}")
            with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
                status, cfg, _ = synthesise(device, package, verilog, lpf,
                                            Path(td), run_id, yv, nv)
                if status == "ok":
                    try:
                        wires = extract_wires_from_config(device, cfg, lift)
                        insert_wires(run_id, wires)
                        L(f"    ok wires={len(wires)}")
                    except Exception as e:
                        update_run(run_id, "extract_fail", error=str(e)[:500])
                        L(f"    extract_fail: {e}")

# ---------------------------------------------------------------------------
# Primitive class: CARRY
# Adder chain forces nextpnr to use carry arcs (FCO/FCI).
# ---------------------------------------------------------------------------
def _carry_verilog(width=8):
    # Keep output internal via XOR reduction so no IO pads needed for s[] bits
    return (
        f"module top(input clk,\n"
        f"           input [{width-1}:0] a, input [{width-1}:0] b,\n"
        f"           output reg parity);\n"
        f"  reg [{width}:0] s;\n"
        f"  always @(posedge clk) begin\n"
        f"    s <= a + b;\n"
        f"    parity <= ^s;\n"
        f"  end\n"
        f"endmodule\n"
    )

def _carry_lpf(clk_pin):
    return (f'LOCATE COMP "clk" SITE "{clk_pin}";\n'
            f'IOBUF PORT "clk" IO_TYPE=LVTTL33;\n')

def fuzz_carry(device, package, yv, nv, L, lift):
    """Fuzz carry chain routing at column-aligned PLC tile groups."""
    chip = lift.chip
    clk  = clk_pin_for(device, package)
    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)

    # Find PLC tiles, group by column, run one carry fuzz per column
    plc_by_col = {}
    for tile in chip.get_all_tiles():
        if tile.info.type == "PLC":
            col = tile.col
            if col not in plc_by_col:
                plc_by_col[col] = []
            plc_by_col[col].append(tile.row)

    for col in sorted(plc_by_col):
        rows = sorted(plc_by_col[col])
        if not rows:
            continue
        tile_row = rows[len(rows)//2]  # pick middle row in column
        site_tag = f"col{col}_R{tile_row}"

        if run_exists(device, package, "carry", "adder8", site_tag):
            continue

        run_id = insert_run(device, package, "carry", "adder8", site_tag,
                            tile_row, col)
        verilog = _carry_verilog(8)
        lpf     = _carry_lpf(clk)

        L(f"  CARRY col={col} anchor=R{tile_row}C{col}")
        with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
            status, cfg, _ = synthesise(device, package, verilog, lpf,
                                        Path(td), run_id, yv, nv)
            if status == "ok":
                try:
                    wires = extract_wires_from_config(device, cfg, lift)
                    insert_wires(run_id, wires)
                    L(f"    ok wires={len(wires)}")
                except Exception as e:
                    update_run(run_id, "extract_fail", error=str(e)[:500])
                    L(f"    extract_fail: {e}")

# ---------------------------------------------------------------------------
# Primitive class: DPRAM / RAMW
# Distributed RAM — exercises RAMW write port + DPRAM read port arcs.
# ---------------------------------------------------------------------------
def _dpram_verilog():
    return """\
module top(
    input clk,
    input we, input [3:0] waddr, input [1:0] wdata,
    input [3:0] raddr, output reg [1:0] rdata
);
  (* ram_style = "distributed" *) reg [1:0] mem [0:15];
  always @(posedge clk) if (we) mem[waddr] <= wdata;
  always @(posedge clk) rdata <= mem[raddr];
endmodule
"""

def _dpram_lpf(clk_pin, tile_row, tile_col):
    lines = [
        f'LOCATE COMP "clk" SITE "{clk_pin}";',
        f'IOBUF PORT "clk" IO_TYPE=LVTTL33;',
        f'LOCATE COMP "mem[0]_0" SITE "R{tile_row}C{tile_col}_SLICEC_RAMW";',
    ]
    return "\n".join(lines)

def fuzz_dpram(device, package, yv, nv, L, lift):
    """Fuzz distributed RAM routing — RAMW write and DPRAM read port arcs."""
    chip = lift.chip
    clk  = clk_pin_for(device, package)
    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)

    for tile in chip.get_all_tiles():
        if tile.info.type != "PLC":
            continue
        tile_row = tile.row
        tile_col = tile.col
        site_tag = f"R{tile_row}C{tile_col}"

        if run_exists(device, package, "dpram", "ramw_dpram", site_tag):
            continue

        run_id = insert_run(device, package, "dpram", "ramw_dpram", site_tag,
                            tile_row, tile_col)
        verilog = _dpram_verilog()
        lpf     = _dpram_lpf(clk, tile_row, tile_col)

        L(f"  DPRAM R{tile_row}C{tile_col}")
        with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
            status, cfg, _ = synthesise(device, package, verilog, lpf,
                                        Path(td), run_id, yv, nv)
            if status == "ok":
                try:
                    wires = extract_wires_from_config(device, cfg, lift)
                    insert_wires(run_id, wires)
                    L(f"    ok wires={len(wires)}")
                except Exception as e:
                    update_run(run_id, "extract_fail", error=str(e)[:500])
                    L(f"    extract_fail: {e}")

# ---------------------------------------------------------------------------
# Primitive class: EBR (block RAM — DP8KC)
# Exercises: write-address/data arcs into EBR tile, read-data arcs out.
# One run per EBR tile, varying width (x1 / x4 / x9).
# ---------------------------------------------------------------------------
def _ebr_verilog(width=4):
    aw = {1: 13, 2: 12, 4: 11, 9: 10, 18: 9}[width]  # address width for given data width
    dw = width if width != 9 else 8  # effective data width (excl parity)
    return (
        f"module top(\n"
        f"  input clk_a, input we_a, input [{aw-1}:0] addr_a, input [{dw-1}:0] din_a,\n"
        f"  input clk_b, input [{aw-1}:0] addr_b, output reg [{dw-1}:0] dout_b\n"
        f");\n"
        f"  (* ram_style = \"block\" *) reg [{dw-1}:0] mem [0:{(1<<aw)-1}];\n"
        f"  always @(posedge clk_a) if (we_a) mem[addr_a] <= din_a;\n"
        f"  always @(posedge clk_b) dout_b <= mem[addr_b];\n"
        f"endmodule\n"
    )

def _ebr_lpf(clk_pin):
    # Use two distinct pads for clk_a and clk_b — they can't share a pin.
    # Pick two consecutive pins that are both present in every package.
    clk_b_pin = str(int(clk_pin) - 1) if clk_pin.isdigit() and int(clk_pin) > 1 else "2"
    lines = [
        f'LOCATE COMP "clk_a" SITE "{clk_pin}";',
        f'IOBUF PORT "clk_a" IO_TYPE=LVTTL33;',
        f'LOCATE COMP "clk_b" SITE "{clk_b_pin}";',
        f'IOBUF PORT "clk_b" IO_TYPE=LVTTL33;',
    ]
    return "\n".join(lines)

def fuzz_ebr(device, package, yv, nv, L, lift):
    """Fuzz EBR (block RAM) routing arcs for all EBR tiles."""
    chip = lift.chip
    clk  = clk_pin_for(device, package)
    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)

    ebr_tiles = [t for t in chip.get_all_tiles()
                 if t.info.type.startswith("EBR") and "DUMMY" not in t.info.type
                 and "END" not in t.info.type]

    if not ebr_tiles:
        L(f"  No EBR tiles found for {device}")
        return

    for tile in ebr_tiles:
        tile_row = tile.row
        tile_col = tile.col

        for width in (1, 4, 9):
            pvariant = f"dp8kc_x{width}"
            site_tag = f"R{tile_row}C{tile_col}"

            if run_exists(device, package, "ebr", pvariant, site_tag):
                continue

            run_id = insert_run(device, package, "ebr", pvariant, site_tag,
                                tile_row, tile_col,
                                design_params=f'{{"width":{width}}}')
            verilog = _ebr_verilog(width)
            lpf     = _ebr_lpf(clk)

            L(f"  EBR {device}/{package} R{tile_row}C{tile_col} width=x{width}")
            with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
                status, cfg, _ = synthesise(device, package, verilog, lpf,
                                            Path(td), run_id, yv, nv)
                if status == "ok":
                    try:
                        wires = extract_wires_from_config(device, cfg, lift)
                        insert_wires(run_id, wires)
                        L(f"    ok wires={len(wires)}")
                    except Exception as e:
                        update_run(run_id, "extract_fail", error=str(e)[:500])
                        L(f"    extract_fail: {e}")

# ---------------------------------------------------------------------------
# Primitive class: PLL (EHXPLLJ / GPLL)
# Exercises clock spine routing from PLL outputs into fabric.
# ---------------------------------------------------------------------------
def _pll_verilog(output):
    """output: 'CLKOP' | 'CLKOS' | 'CLKOS2' | 'CLKOS3'"""
    ports = dict(CLKOP="clkop", CLKOS="clkos", CLKOS2="clkos2", CLKOS3="clkos3")
    out   = ports[output]
    others = [f".{k}()" for k, v in ports.items() if k != output]
    other_str = ", ".join(others)
    return (
        f"(* keep *) module top(input clkin, output reg q);\n"
        f"  wire {out};\n"
        f"  (* keep *) EHXPLLJ #(\n"
        f"    .CLKI_DIV(1), .CLKFB_DIV(9), .CLKOP_DIV(1),\n"
        f"    .CLKOS_DIV(3), .CLKOS2_DIV(7), .CLKOS3_DIV(1),\n"
        f"    .FEEDBK_PATH(\"INT_OP\")\n"
        f"  ) pll (.CLKI(clkin), .CLKFB({out}),\n"
        f"         .{output}({out}), {other_str});\n"
        f"  always @(posedge {out}) q <= ~q;\n"
        f"endmodule\n"
    )

def _pll_lpf(clk_pin):
    return (f'LOCATE COMP "clkin" SITE "{clk_pin}";\n'
            f'IOBUF PORT "clkin" IO_TYPE=LVTTL33;\n')

def fuzz_pll(device, package, yv, nv, L, lift):
    """Fuzz PLL output routing into the clock spine."""
    chip = lift.chip
    clk  = clk_pin_for(device, package)
    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)

    pll_tiles = [t for t in chip.get_all_tiles()
                 if "GPLL" in t.info.type or "PLL" in t.info.type]

    if not pll_tiles:
        L(f"  No PLL tiles found for {device}")
        return

    for tile in pll_tiles:
        tile_row = tile.row
        tile_col = tile.col
        for output in ("CLKOP", "CLKOS", "CLKOS2", "CLKOS3"):
            site_tag = f"R{tile_row}C{tile_col}"
            pvariant = f"ehxpllj_{output.lower()}"

            if run_exists(device, package, "pll", pvariant, site_tag):
                continue

            run_id = insert_run(device, package, "pll", pvariant, site_tag,
                                tile_row, tile_col, design_params=f'{{"output":"{output}"}}')
            verilog = _pll_verilog(output)
            lpf     = _pll_lpf(clk)

            L(f"  PLL {device}/{package} R{tile_row}C{tile_col} {output}")
            with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
                status, cfg, _ = synthesise(device, package, verilog, lpf,
                                            Path(td), run_id, yv, nv)
                if status == "ok":
                    try:
                        wires = extract_wires_from_config(device, cfg, lift)
                        insert_wires(run_id, wires)
                        L(f"    ok wires={len(wires)}")
                    except Exception as e:
                        update_run(run_id, "extract_fail", error=str(e)[:500])
                        L(f"    extract_fail: {e}")

# ---------------------------------------------------------------------------
# Primitive class: IOLOGIC (IDDR / ODDR)
# Exercises edge-clock (ECLK) routing and double-rate data arcs.
# ---------------------------------------------------------------------------
def _iddr_verilog(pin, clk_pin):
    p = f"p{pin}"
    return (
        f"module top(input {p}, input eclk, output reg q0, output reg q1);\n"
        f"  (* keep *) IDDRX1F iddr(.D({p}), .SCLK(eclk), .RST(1'b0),\n"
        f"                           .Q0(q0), .Q1(q1));\n"
        f"endmodule\n"
    )

def _oddr_verilog(pin, clk_pin):
    p = f"p{pin}"
    return (
        f"module top(input d0, input d1, input eclk, output {p});\n"
        f"  (* keep *) ODDRX1F oddr(.D0(d0), .D1(d1), .SCLK(eclk), .Q({p}));\n"
        f"endmodule\n"
    )

def _iologic_lpf(pin, clk_pin):
    p = f"p{pin}"
    return (f'LOCATE COMP "{p}" SITE "{pin}";\n'
            f'IOBUF PORT "{p}" IO_TYPE=LVTTL33;\n'
            f'LOCATE COMP "eclk" SITE "{clk_pin}";\n'
            f'IOBUF PORT "eclk" IO_TYPE=LVTTL33;\n')

def fuzz_iologic(device, package, yv, nv, L, lift):
    """Fuzz IDDR/ODDR at every IO pad."""
    iodb = mx.load_iodb(device)
    pkg_map = iodb["packages"].get(package, {})
    if not pkg_map:
        return

    clk = clk_pin_for(device, package)
    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)

    site_list = sorted(set(
        (s["row"], s["col"], s["pio"]) for s in pkg_map.values()
    ))

    for (tile_row, tile_col, pio) in site_list:
        pkg_pin = next(
            (pin for pin, s in pkg_map.items()
             if s["row"] == tile_row and s["col"] == tile_col and s["pio"] == pio),
            None
        )
        if pkg_pin is None or pkg_pin == clk:
            continue

        for prim, mk_v in (("iddr", _iddr_verilog), ("oddr", _oddr_verilog)):
            site_tag = f"R{tile_row}C{tile_col}_{pio}"
            if run_exists(device, package, "iologic", prim, site_tag):
                continue

            run_id = insert_run(device, package, "iologic", prim, site_tag,
                                tile_row, tile_col)
            verilog = mk_v(pkg_pin, clk)
            lpf     = _iologic_lpf(pkg_pin, clk)

            L(f"  IOLOGIC/{prim} {device}/{package} R{tile_row}C{tile_col} {pio}")
            with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
                status, cfg, _ = synthesise(device, package, verilog, lpf,
                                            Path(td), run_id, yv, nv)
                if status == "ok":
                    try:
                        wires = extract_wires_from_config(device, cfg, lift)
                        insert_wires(run_id, wires)
                        L(f"    ok wires={len(wires)}")
                    except Exception as e:
                        update_run(run_id, "extract_fail", error=str(e)[:500])
                        L(f"    extract_fail: {e}")

# ---------------------------------------------------------------------------
# Primitive class: EFB (all sub-blocks)
# ---------------------------------------------------------------------------
_EFB_VARIANTS = {
    # Individual sub-blocks
    "wb":    ("ENABLED",  "DISABLED", "DISABLED", "DISABLED", "DISABLED", "DISABLED"),
    "spi":   ("DISABLED", "ENABLED",  "DISABLED", "DISABLED", "DISABLED", "DISABLED"),
    "i2c1":  ("DISABLED", "DISABLED", "ENABLED",  "DISABLED", "DISABLED", "DISABLED"),
    "i2c2":  ("DISABLED", "DISABLED", "DISABLED", "ENABLED",  "DISABLED", "DISABLED"),
    "timer": ("DISABLED", "DISABLED", "DISABLED", "DISABLED", "ENABLED",  "DISABLED"),
    "ufm":   ("DISABLED", "DISABLED", "DISABLED", "DISABLED", "DISABLED", "ENABLED"),
    # Pairs — exercises routing shared between co-enabled sub-blocks
    "wb_spi":   ("ENABLED", "ENABLED", "DISABLED", "DISABLED", "DISABLED", "DISABLED"),
    "wb_i2c1":  ("ENABLED", "DISABLED", "ENABLED", "DISABLED", "DISABLED", "DISABLED"),
    "wb_timer": ("ENABLED", "DISABLED", "DISABLED", "DISABLED", "ENABLED", "DISABLED"),
    "wb_ufm":   ("ENABLED", "DISABLED", "DISABLED", "DISABLED", "DISABLED", "ENABLED"),
    "spi_timer":("DISABLED","ENABLED",  "DISABLED", "DISABLED", "ENABLED", "DISABLED"),
    # All enabled — full EFB routing
    "all":   ("ENABLED",  "ENABLED",  "ENABLED",  "ENABLED",  "ENABLED",  "ENABLED"),
}

def _efb_verilog(variant):
    wb, spi, i2c1, i2c2, tc, ufm = _EFB_VARIANTS[variant]
    return (
        f'(* keep *) module top(input clk, input wb_stb, input wb_cyc,\n'
        f'    input wb_we, input [7:0] wb_adr, input [7:0] wb_dat_i,\n'
        f'    output reg [7:0] wb_dat_o_reg, output reg wb_ack_reg);\n'
        f'  wire [7:0] wbdato; wire wbacko;\n'
        f'  (* keep *) EFB #(\n'
        f'    .EFB_WB("{wb}"), .EFB_SPI("{spi}"),\n'
        f'    .EFB_I2C1("{i2c1}"), .EFB_I2C2("{i2c2}"),\n'
        f'    .EFB_TC("{tc}")\n'
        f'  ) efb (\n'
        f'    .WBCLKI(clk), .WBSTBI(wb_stb), .WBCYCI(wb_cyc),\n'
        f'    .WBWEI(wb_we),\n'
        f'    .WBADRI7(wb_adr[7]),.WBADRI6(wb_adr[6]),.WBADRI5(wb_adr[5]),\n'
        f'    .WBADRI4(wb_adr[4]),.WBADRI3(wb_adr[3]),.WBADRI2(wb_adr[2]),\n'
        f'    .WBADRI1(wb_adr[1]),.WBADRI0(wb_adr[0]),\n'
        f'    .WBDATI7(wb_dat_i[7]),.WBDATI6(wb_dat_i[6]),.WBDATI5(wb_dat_i[5]),\n'
        f'    .WBDATI4(wb_dat_i[4]),.WBDATI3(wb_dat_i[3]),.WBDATI2(wb_dat_i[2]),\n'
        f'    .WBDATI1(wb_dat_i[1]),.WBDATI0(wb_dat_i[0]),\n'
        f'    .WBDATO7(wbdato[7]),.WBDATO6(wbdato[6]),.WBDATO5(wbdato[5]),\n'
        f'    .WBDATO4(wbdato[4]),.WBDATO3(wbdato[3]),.WBDATO2(wbdato[2]),\n'
        f'    .WBDATO1(wbdato[1]),.WBDATO0(wbdato[0]),\n'
        f'    .WBACKO(wbacko));\n'
        f'  always @(posedge clk) begin\n'
        f'    wb_dat_o_reg <= wbdato;\n'
        f'    wb_ack_reg   <= wbacko;\n'
        f'  end\nendmodule\n'
    )

def _efb_lpf(clk_pin):
    return (f'LOCATE COMP "clk" SITE "{clk_pin}";\n'
            f'IOBUF PORT "clk" IO_TYPE=LVTTL33;\n')

def fuzz_efb(device, package, yv, nv, L, lift):
    """Fuzz all EFB sub-block variants."""
    clk = clk_pin_for(device, package)
    site_tag = "EFB"
    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)

    for variant in _EFB_VARIANTS:
        if run_exists(device, package, "efb", variant, site_tag):
            continue

        run_id = insert_run(device, package, "efb", variant, site_tag,
                            design_params=f'{{"variant":"{variant}"}}')
        verilog = _efb_verilog(variant)
        lpf     = _efb_lpf(clk)

        L(f"  EFB/{variant} {device}/{package}")
        with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
            status, cfg, _ = synthesise(device, package, verilog, lpf,
                                        Path(td), run_id, yv, nv)
            if status == "ok":
                try:
                    wires = extract_wires_from_config(device, cfg, lift)
                    insert_wires(run_id, wires)
                    L(f"    ok wires={len(wires)}")
                except Exception as e:
                    update_run(run_id, "extract_fail", error=str(e)[:500])
                    L(f"    extract_fail: {e}")

# ---------------------------------------------------------------------------
# Primitive class: LONGLINE / GLOBAL (HPBX/VPTX spanning wires)
# Forces a high-fanout net so nextpnr uses the global routing network.
# ---------------------------------------------------------------------------
def _longline_verilog(fanout=32):
    outputs = " ".join(f"output reg q{i}," for i in range(fanout))
    assigns = "\n  ".join(f"q{i} <= d;" for i in range(fanout))
    return (
        f"module top(input clk, input d, {outputs} output reg dummy);\n"
        f"  always @(posedge clk) begin\n"
        f"    {assigns}\n"
        f"    dummy <= ^({' ^ '.join(f'q{i}' for i in range(fanout))});\n"
        f"  end\nendmodule\n"
    )

def _longline_lpf(clk_pin):
    return (f'LOCATE COMP "clk" SITE "{clk_pin}";\n'
            f'IOBUF PORT "clk" IO_TYPE=LVTTL33;\n')

def fuzz_longlines(device, package, yv, nv, L, lift):
    """Fuzz long-line / global wire routing with high-fanout nets."""
    clk = clk_pin_for(device, package)
    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)

    for fanout in (16, 64):
        pvariant = f"hpbx_fanout{fanout}"
        site_tag = "global"

        if run_exists(device, package, "longline", pvariant, site_tag):
            continue

        run_id = insert_run(device, package, "longline", pvariant, site_tag,
                            design_params=f'{{"fanout":{fanout}}}')
        verilog = _longline_verilog(fanout)
        lpf     = _longline_lpf(clk)

        L(f"  LONGLINE {device}/{package} fanout={fanout}")
        with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
            status, cfg, _ = synthesise(device, package, verilog, lpf,
                                        Path(td), run_id, yv, nv)
            if status == "ok":
                try:
                    wires = extract_wires_from_config(device, cfg, lift)
                    insert_wires(run_id, wires)
                    L(f"    ok wires={len(wires)}")
                except Exception as e:
                    update_run(run_id, "extract_fail", error=str(e)[:500])
                    L(f"    extract_fail: {e}")

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def report():
    con = _conn()
    cur = con.cursor()

    print("=== Coverage summary (by primitive class) ===")
    cur.execute(
        "SELECT device, package, primitive_class, primitive_variant, "
        "total_runs, ok_runs, pnr_fail_runs, synth_fail_runs "
        "FROM fuzz_coverage_summary"
    )
    rows = cur.fetchall()
    colnames = [d[0] for d in cur.description]
    print(f"{'device':<18} {'pkg':<10} {'class':<12} {'variant':<22} "
          f"{'total':>6} {'ok':>5} {'pnr_fail':>9} {'synth_fail':>11}")
    print("-" * 100)
    for row in rows:
        r = dict(zip(colnames, row))
        print(f"{r['device']:<18} {r['package']:<10} {r['primitive_class']:<12} "
              f"{r['primitive_variant']:<22} {r['total_runs']:>6} {r['ok_runs']:>5} "
              f"{r['pnr_fail_runs']:>9} {r['synth_fail_runs']:>11}")

    print("\n=== Wire globalise rate (ok runs only) ===")
    cur.execute(
        "SELECT device, primitive_class, total_wires, resolved_wires, pct_resolved "
        "FROM fuzz_wire_globalise_rate"
    )
    rates = cur.fetchall()
    colnames = [d[0] for d in cur.description]
    print(f"{'device':<18} {'class':<12} {'total':>7} {'resolved':>9} {'%':>6}")
    print("-" * 58)
    for row in rates:
        r = dict(zip(colnames, row))
        print(f"{r['device']:<18} {r['primitive_class']:<12} "
              f"{r['total_wires']:>7} {r['resolved_wires']:>9} {r['pct_resolved']:>6}")

    print("\n=== Missing wires (top 30) ===")
    cur.execute(
        "SELECT wire_name, tile_row, tile_col, device, primitive_class, missing_count "
        "FROM fuzz_missing_wires LIMIT 30"
    )
    missing = cur.fetchall()
    colnames = [d[0] for d in cur.description]
    if not missing:
        print("  None — all wires globalise successfully.")
    else:
        print(f"{'wire_name':<35} {'row':>4} {'col':>4} {'device':<18} {'class':<12} {'missing':>8}")
        print("-" * 85)
        for row in missing:
            r = dict(zip(colnames, row))
            print(f"{r['wire_name']:<35} {r['tile_row']:>4} {r['tile_col']:>4} "
                  f"{r['device']:<18} {r['primitive_class']:<12} {r['missing_count']:>8}")


def compare():
    """Regression report: sites where bitstream hash changed across toolchain versions."""
    con = _conn()
    cur = con.cursor()

    cur.execute(
        "SELECT device, package, primitive_class, primitive_variant, site_tag, "
        "yosys_a, nextpnr_a, yosys_b, nextpnr_b, hash_a, hash_b, run_at_a, run_at_b "
        "FROM fuzz_regressions ORDER BY device, primitive_class, site_tag"
    )
    rows = cur.fetchall()
    reg_cols = [d[0] for d in cur.description]

    cur.execute(
        "SELECT yosys_version, nextpnr_version, recorded_at FROM fuzz_toolchain_versions "
        "ORDER BY recorded_at"
    )
    tv_rows = cur.fetchall()
    tv_cols = [d[0] for d in cur.description]

    print("=== Toolchain versions seen ===")
    for row in tv_rows:
        r = dict(zip(tv_cols, row))
        print(f"  yosys={r['yosys_version']!r:<50}  nextpnr={r['nextpnr_version']!r}")

    print(f"\n=== Regressions (bitstream hash changed between runs): {len(rows)} ===")
    if not rows:
        print("  None — all repeated runs produced identical bitstreams.")
        return

    print(f"{'device':<18} {'class':<10} {'variant':<20} {'site':<22} "
          f"{'hash_a':<18} {'hash_b':<18} note")
    print("-" * 110)
    for row in rows:
        r = dict(zip(reg_cols, row))
        note = ("toolchain_diff"
                if r["yosys_a"] != r["yosys_b"] or r["nextpnr_a"] != r["nextpnr_b"]
                else "same_toolchain_diff_result")
        print(f"{r['device']:<18} {r['primitive_class']:<10} {r['primitive_variant']:<20} "
              f"{r['site_tag']:<22} {r['hash_a']:<18} {r['hash_b']:<18} {note}")

# ---------------------------------------------------------------------------
# Main fuzzer loop
# ---------------------------------------------------------------------------
def _run_one_job(job, yv, nv, L, lift):
    """Execute a single fuzz job dict. Called from thread pool."""
    pclass   = job["pclass"]
    pvariant = job["pvariant"]
    site_tag = job["site_tag"]
    device   = job["device"]
    package  = job["package"]

    if run_exists(device, package, pclass, pvariant, site_tag):
        return "skip"

    run_id = insert_run(device, package, pclass, pvariant, site_tag,
                        job.get("tile_row"), job.get("tile_col"),
                        job.get("design_params"))
    verilog = job["verilog"]
    lpf     = job["lpf"]

    L(f"  {pclass}/{pvariant} {device}/{package} {site_tag}")

    _fuzz_tmp = _ROOT / "fpga" / "tmp" / "fuzz_work"
    _fuzz_tmp.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(_fuzz_tmp)) as td:
        status, cfg, _ = synthesise(device, package, verilog, lpf,
                                    Path(td), run_id, yv, nv)
        if status == "ok":
            try:
                wires = extract_wires_from_config(device, cfg, lift)
                insert_wires(run_id, wires)
                L(f"    ok wires={len(wires)}")
            except Exception as e:
                update_run(run_id, "extract_fail", error=str(e)[:500])
                L(f"    extract_fail: {e}")
    return status


def collect_jobs(device, package, lift):
    """Return list of job dicts for all primitives for this device/package."""
    jobs = []
    iodb    = mx.load_iodb(device)
    pkg_map = iodb["packages"].get(package, {})
    clk     = clk_pin_for(device, package)
    chip    = lift.chip

    # ---- PAD ----
    all_cols = [s["col"] for s in pkg_map.values()] if pkg_map else [0]
    max_col  = max(all_cols)
    site_list = sorted(set(
        (s["row"], s["col"], s["pio"]) for s in pkg_map.values()
    ))
    for (tile_row, tile_col, pio) in site_list:
        pkg_pin = next(
            (pin for pin, s in pkg_map.items()
             if s["row"] == tile_row and s["col"] == tile_col and s["pio"] == pio),
            None
        )
        if pkg_pin is None:
            continue
        ck = clk if clk != pkg_pin else ("1" if pkg_pin != "1" else "2")
        for prim in _PAD_PRIMITIVES:
            if prim == "ff_edge_hop" and (tile_col < max_col - 1 or tile_col < 2):
                continue
            ff_col = tile_col - 1 if prim == "ff_edge_hop" else None
            jobs.append(dict(
                pclass="pad", pvariant=prim,
                site_tag=f"R{tile_row}C{tile_col}_{pio}",
                device=device, package=package,
                tile_row=tile_row, tile_col=tile_col,
                verilog=_pad_verilog(pkg_pin, prim, ck),
                lpf=_pad_lpf(pkg_pin, prim, ck, ff_col, tile_row),
            ))

    # ---- LUT ----
    for tile in chip.get_all_tiles():
        if tile.info.type != "PLC":
            continue
        for n in (2, 4):
            jobs.append(dict(
                pclass="lut", pvariant=f"lut{n}",
                site_tag=f"R{tile.row}C{tile.col}",
                device=device, package=package,
                tile_row=tile.row, tile_col=tile.col,
                verilog=_lut_verilog(n), lpf=_lut_lpf(clk),
            ))

    # ---- CARRY ----
    plc_by_col = {}
    for tile in chip.get_all_tiles():
        if tile.info.type == "PLC":
            plc_by_col.setdefault(tile.col, []).append(tile.row)
    for col, rows in sorted(plc_by_col.items()):
        tile_row = sorted(rows)[len(rows)//2]
        jobs.append(dict(
            pclass="carry", pvariant="adder8",
            site_tag=f"col{col}_R{tile_row}",
            device=device, package=package,
            tile_row=tile_row, tile_col=col,
            verilog=_carry_verilog(8), lpf=_carry_lpf(clk),
        ))

    # ---- DPRAM ----
    for tile in chip.get_all_tiles():
        if tile.info.type != "PLC":
            continue
        jobs.append(dict(
            pclass="dpram", pvariant="ramw_dpram",
            site_tag=f"R{tile.row}C{tile.col}",
            device=device, package=package,
            tile_row=tile.row, tile_col=tile.col,
            verilog=_dpram_verilog(), lpf=_dpram_lpf(clk, tile.row, tile.col),
        ))

    # ---- EBR ----
    ebr_tiles = [t for t in chip.get_all_tiles()
                 if t.info.type.startswith("EBR") and "DUMMY" not in t.info.type
                 and "END" not in t.info.type]
    for tile in ebr_tiles:
        for width in (1, 4, 9):
            jobs.append(dict(
                pclass="ebr", pvariant=f"dp8kc_x{width}",
                site_tag=f"R{tile.row}C{tile.col}",
                device=device, package=package,
                tile_row=tile.row, tile_col=tile.col,
                design_params=f'{{"width":{width}}}',
                verilog=_ebr_verilog(width), lpf=_ebr_lpf(clk),
            ))

    # ---- PLL ----
    pll_tiles = [t for t in chip.get_all_tiles()
                 if "GPLL" in t.info.type or "PLL" in t.info.type]
    for tile in pll_tiles:
        for output in ("CLKOP", "CLKOS", "CLKOS2", "CLKOS3"):
            jobs.append(dict(
                pclass="pll", pvariant=f"ehxpllj_{output.lower()}",
                site_tag=f"R{tile.row}C{tile.col}",
                device=device, package=package,
                tile_row=tile.row, tile_col=tile.col,
                design_params=f'{{"output":"{output}"}}',
                verilog=_pll_verilog(output), lpf=_pll_lpf(clk),
            ))

    # ---- IOLOGIC ----
    for (tile_row, tile_col, pio) in site_list:
        pkg_pin = next(
            (pin for pin, s in pkg_map.items()
             if s["row"] == tile_row and s["col"] == tile_col and s["pio"] == pio),
            None
        )
        if pkg_pin is None or pkg_pin == clk:
            continue
        for prim, mk_v in (("iddr", _iddr_verilog), ("oddr", _oddr_verilog)):
            jobs.append(dict(
                pclass="iologic", pvariant=prim,
                site_tag=f"R{tile_row}C{tile_col}_{pio}",
                device=device, package=package,
                tile_row=tile_row, tile_col=tile_col,
                verilog=mk_v(pkg_pin, clk), lpf=_iologic_lpf(pkg_pin, clk),
            ))

    # ---- EFB ----
    for variant in _EFB_VARIANTS:
        jobs.append(dict(
            pclass="efb", pvariant=variant,
            site_tag="EFB",
            device=device, package=package,
            design_params=f'{{"variant":"{variant}"}}',
            verilog=_efb_verilog(variant), lpf=_efb_lpf(clk),
        ))

    # ---- LONGLINE ----
    for fanout in (16, 64):
        jobs.append(dict(
            pclass="longline", pvariant=f"hpbx_fanout{fanout}",
            site_tag="global",
            device=device, package=package,
            design_params=f'{{"fanout":{fanout}}}',
            verilog=_longline_verilog(fanout), lpf=_longline_lpf(clk),
        ))

    return jobs


def fuzz_device_package(device, package, yv, nv, L, jobs_n=1):
    try:
        lift = mx.MachXO2Lift(device)
    except Exception as e:
        L(f"SKIP {device}: lift init failed: {e}")
        return

    L(f"=== {device} / {package} (jobs={jobs_n}) ===")
    jobs = collect_jobs(device, package, lift)
    pending = [j for j in jobs
               if not run_exists(j["device"], j["package"],
                                 j["pclass"], j["pvariant"], j["site_tag"])]
    L(f"  {len(jobs)} total jobs, {len(pending)} pending, {len(jobs)-len(pending)} already done")

    if not pending:
        return

    if jobs_n <= 1:
        for job in pending:
            _run_one_job(job, yv, nv, L, lift)
    else:
        with ThreadPoolExecutor(max_workers=jobs_n) as pool:
            futures = {pool.submit(_run_one_job, job, yv, nv, L, lift): job
                       for job in pending}
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    job = futures[fut]
                    L(f"  EXCEPTION {job['pclass']}/{job['pvariant']} {job['site_tag']}: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs",        type=int, default=1,
                    help="Parallel synthesis workers (default 1; try 24 on a big machine)")
    ap.add_argument("--report",      action="store_true")
    ap.add_argument("--compare",     action="store_true",
                    help="Show regression report (bitstream hash changes across toolchain versions)")
    ap.add_argument("--kill",        action="store_true")
    ap.add_argument("--all-devices", action="store_true",
                    help="Also fuzz all other LCMXO2 devices/packages (slow)")
    ap.add_argument("--device",  help="Fuzz only this device (overrides --all-devices)")
    ap.add_argument("--package", help="Fuzz only this package")
    args = ap.parse_args()

    if args.kill:
        import os as _os
        result = subprocess.run(["pgrep", "-f", Path(__file__).name],
                                capture_output=True, text=True)
        pids = [int(p) for p in result.stdout.split()
                if p and int(p) != _os.getpid()]
        if not pids:
            print("no running instances found")
        for pid in pids:
            _os.kill(pid, signal.SIGTERM)
            print(f"killed PID {pid}")
        sys.exit(0)

    print("DB: fpga_re (Postgres)", flush=True)

    if args.report:
        report()
        return

    if args.compare:
        compare()
        return

    _LOG.parent.mkdir(parents=True, exist_ok=True)

    with open(_LOG, "a") as log_fh:
        ts = _now()
        log_fh.write(f"\n=== fuzz_machxo2_full.py started {ts} ===\n")
        log_fh.flush()

        def L(msg):
            line = f"{_now()} {msg}"
            print(line, flush=True)
            log_fh.write(line + "\n")
            log_fh.flush()

        yv, nv = capture_toolchain()
        L(f"Toolchain: yosys={yv!r}  nextpnr={nv!r}")

        if args.device:
            devices_packages = [(args.device, args.package or PRIMARY_PACKAGE)]
        elif args.all_devices:
            # Primary device/package first, then everything else
            devices_packages = [(PRIMARY_DEVICE, PRIMARY_PACKAGE)]
            for dev in ALL_DEVICES:
                iodb = mx.load_iodb(dev)
                for pkg in sorted(iodb["packages"].keys()):
                    if (dev, pkg) != (PRIMARY_DEVICE, PRIMARY_PACKAGE):
                        devices_packages.append((dev, pkg))
        else:
            devices_packages = [(PRIMARY_DEVICE, PRIMARY_PACKAGE)]

        L(f"Target: {len(devices_packages)} device/package combinations")

        for device, package in devices_packages:
            try:
                fuzz_device_package(device, package, yv, nv, L, jobs_n=args.jobs)
            except KeyboardInterrupt:
                L("Interrupted — DB is safe, restart to resume.")
                sys.exit(0)
            except Exception as e:
                L(f"ERROR {device}/{package}: {e}")

        L("=== DONE ===")
        report()


if __name__ == "__main__":
    main()
