#!/usr/bin/env python3
"""Fuzz Cyclone V block-mux values against real Quartus compiles
(issue #103: independent verification of Mistral's cv_block_muxes claims).

Mistral's `cv_block_muxes` rows describe bit positions and named values.
This script compiles a small Quartus design per knob/config, decompiles the
.rbf with mistral-cv, and compares what Mistral decodes against what the
Quartus setting should have produced.

Dump targets (--dump-target):

  gpio  (pram, `m`)   named value of GPIO drive_strength, per pin.
                      Verdict = decoded name for the pin == requested name.
  opt   (oram)        global option bits (`o` lines).  Mistral prints the
                      RAW value of each non-default option, so the verdict
                      compares the raw bit with the value the QSF setting
                      should set, on both the knob build and the default
                      build.  The bitstream must change (rbf diff vs the
                      default build) or the verdict is INCONCLUSIVE.
  lab   (cram, `g`/`i`)  LAB control muxes (clock/enable/clear/load selects,
                      inversions, tmode/bmode).  Probes pin registers to one LAB
                      (LAB_PROBES); checks in LAB_CHECKS; one verdict per row.
  mlab  (cram, `g`/`i`)  same, with the MLAB probe (ramstyle MLAB, 16x1 RAM).
  m10k  (cram, `m`/`n`/`b`)  M10K port widths and true-dual-port mode, from
                      single/simple/true dual-port RAM inferred at each
                      width.  Verdict = decoded value on every M10K tile
                      == the width/mode the RTL asks for.

Verdicts (all targets):
  MATCH        decoded value == expected value
  MISMATCH     decoded value differs from expected (recorded, not a script failure)
  INCONCLUSIVE no Quartus knob, Quartus rejected the setting, Quartus applied
               the setting but the bitstream did not change, or no tile was
               decoded.  Never silently skipped, never forced to MATCH.

Limits (stated, not hidden):
  * `mistral-cv decomp` prints opt bits with their default suppressed, so an
    absent `o` line means "equal to Mistral's default".  The expected value
    for the default build is checked the same way.
  * Only the port-width and true-dual-port M10K muxes have an independent
    expectation.  fast_write / outclr_en / output_sel are recorded as observed
    only (INCONCLUSIVE); no Quartus knob maps to them directly.

Flow:
    quartus_map -> quartus_fit -> quartus_asm -> quartus_cpf -c (.rbf)
    -> mistral-cv decomp -> parse `o` (opt) or `s M10K.*` (m10k) / `s GPIO.*` lines
    (opt also cross-checks jtag_id against the assembler report's JTAG usercode)

Device: 5CEBA4U19C8 (U19 = 484-pin package; pin names checked against the
Quartus IBIS package file 5ceba4_u4840.xml).

Usage:
    python3 scripts/cyclonev_blockmux_fuzz.py --value v3p0_lvttl_8ma      # gpio (default)
    python3 scripts/cyclonev_blockmux_fuzz.py --list
    python3 scripts/cyclonev_blockmux_fuzz.py --dump-target opt --all
    python3 scripts/cyclonev_blockmux_fuzz.py --dump-target m10k --all

Output:
    tmp/logs/cyclonev_blockmux_fuzz.log        -- full run log
    tmp/cyclonev_blockmux_fuzz/<slug>/         -- qsf/v/rbf/bt per build
    tmp/cyclonev_blockmux_fuzz/results.json    -- verdict per check (merged)
Exit code: 0 when every requested check got a verdict, 2 on usage error.
A MISMATCH is a finding recorded in results.json, not a script failure.
"""
import argparse
import json
import logging
import math
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
# Resolve the SQLite file against the repo, not the launch directory.
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "pluribus.db"))

import toolchain  # noqa: E402

QUARTUS_BIN = Path(toolchain.quartus_bin())
MISTRAL_CV = Path(toolchain.mistral_cv())
DEVICE = "5CEBA4U19C8"
DEFAULT_PIN = "PIN_F8"          # bank 8A user I/O, single-ended (IBIS u4840)
WORK_DIR = REPO / "tmp" / "cyclonev_blockmux_fuzz"
LOG_PATH = REPO / "tmp" / "logs" / "cyclonev_blockmux_fuzz.log"
RESULTS_PATH = WORK_DIR / "results.json"

# Overall limits = 2-4x the measured one-design time on this host (quartus_map
# ~4s, quartus_fit ~8s, quartus_asm ~1-2s, cpf <1s, mistral-cv decomp ~1.5s;
# whole chain 12-14s, docs/cyclonev-blockmux-fuzz-status.md).  Expiry is logged
# with the limit and the command, and the check is INCONCLUSIVE.
TIMEOUT_QUARTUS_FAST = 30
TIMEOUT_QUARTUS_FIT = 60
# True dual-port RAM fit: one uncapped run took 147.2s wall at loadavg 15-17
# (tmp/logs/tdp_fit_timing.log, 2026-10-23). 3x that, rounded.
TIMEOUT_QUARTUS_FIT_TDP = 450
TIMEOUT_MISTRAL = 15

# ── GPIO knob map (unchanged from the drive_strength round) ──────────────────
_LVCMOS_TTL_KNOBS = [
    (re.compile(r"^v3p0_lvttl_(\d+)ma$"), "3.0-V LVTTL"),
    (re.compile(r"^v3p3_lvttl_(\d+)ma$"), "3.3-V LVTTL"),
    (re.compile(r"^v3p0_lvcmos_(\d+)ma$"), "3.0-V LVCMOS"),
    (re.compile(r"^v1p8_(\d+)ma$"), "1.8 V"),
    (re.compile(r"^v2p5_(\d+)ma$"), "2.5 V"),
    (re.compile(r"^v1p5_(\d+)ma$"), "1.5 V"),
    (re.compile(r"^v1p2_(\d+)ma$"), "1.2 V"),
]
# Class I assumed for every SSTL/HSTL name; a wrong class decodes to another name (MISMATCH).
_SSTL_HSTL_KNOBS = [
    (re.compile(r"^hstl12_(\d+)ma$"), "HSTL-12 Class I"),
    (re.compile(r"^hstl15_(\d+)ma$"), "HSTL-15 Class I"),
    (re.compile(r"^hstl18_(\d+)ma$"), "HSTL-18 Class I"),
    (re.compile(r"^sstl15_(\d+)ma$"), "SSTL-15 Class I"),
    (re.compile(r"^sstl18_(\d+)ma$"), "SSTL-18 Class I"),
    (re.compile(r"^sstl2_(\d+)ma$"), "SSTL-2 Class I"),
]
MUX = "drive_strength"       # gpio mux under test
GPIO_KNOBS = {"drive_strength": _LVCMOS_TTL_KNOBS + _SSTL_HSTL_KNOBS}

# ── opt knobs ────────────────────────────────────────────────────────────────
# mux -> spec.  "qsf": global assignments applied to the knob build (the
# default build has none).  "knob"/"default": the RAW value the mux name
# predicts for each build.  None = no expectation (observed only).
# Sources: data/opt-mux.txt defaults; assignment_defaults*.qdf names; the
# knob builds listed in docs/cyclonev-blockmux-fuzz-status.md.
OPT_KNOBS = {
    "jtag_id": {"qsf": ["USE_CHECKSUM_AS_USERCODE Off"], "kind": "usercode"},
    "retry_config_on_error_en": {"qsf": ["AUTO_RESTART_CONFIGURATION Off"],
                                 "knob": 0, "default": 1},
    "oct_done_dis": {"qsf": ["ENABLE_OCT_DONE On"], "knob": 0, "default": 1},
    "nceo_dis": {"qsf": ["ENABLE_NCEO_OUTPUT On"], "knob": 0, "default": 1},
    "allow_device_wide_output_enable_dis": {"qsf": ["ENABLE_DEVICE_WIDE_OE On"],
                                            "knob": 0, "default": 1},
    "device_wide_reset_en": {"qsf": ["ENABLE_DEVICE_WIDE_RESET On"],
                             "knob": 1, "default": 0},
    "cvp_conf_done_en": {"qsf": ["ENABLE_CVP_CONFDONE On"], "knob": 1, "default": 0},
    "release_clears_before_tristates_dis": {"qsf": ["RELEASE_CLEARS_BEFORE_TRI_STATES On"],
                                            "knob": 0, "default": 1},
    "compression_dis": {"qsf": ["COMPRESSION_MODE On"], "knob": 0, "default": 1},
    "crc_error_detection_en": {"qsf": ["CRC_ERROR_CHECKING On"], "knob": 1, "default": 0},
    "external_clk_spi": {"qsf": ["CLOCK_SOURCE External",
                                 'CONFIGURATION_CLOCK_FREQUENCY "25 MHz"'],
                         "knob": 25, "default": 100},
    "start_up_clock": {"qsf": ["USER_START_UP_CLOCK On"], "knob": None, "default": 63},
}
# Rows with no Quartus knob tried.  Reason is recorded in results.json.
OPT_UNTESTED = {
    "idcode": "no Quartus assignment identified",
    "crc_divide_order": "no Quartus assignment name in assignment_defaults*.qdf",
    "drive_strength": "no Quartus assignment identified",
    "cvpcie_mode": "CVP_MODE 'Auto' rejected (Error 125036); legal value not identified",
    "iocsr_ready_from_csr_done_en": "no Quartus assignment identified",
    "opt_a": "no Quartus assignment identified",
    "opt_b": "no Quartus assignment identified (constant ffffff40.2dffffff in every build)",
}

# ── m10k configs ─────────────────────────────────────────────────────────────
M10K_WIDTHS = [1, 2, 5, 10, 20, 40]          # a_data_width / b_data_width values
M10K_DEPTH = {1: 8192, 2: 4096, 5: 2048, 10: 1024, 20: 512, 40: 256}
# sp/sdp/tdp: inferred from Verilog.  tdpip: explicit altsyncram BIDIR_DUAL_PORT
# (inference of "tdp" flattens to logic, 0 M10K bits -- see status doc).
M10K_STYLES = ["sp", "sdp", "tdp", "tdpip"]
M10K_CHECKED = ["a_data_width", "b_data_width", "true_dual_port"]
M10K_OBSERVED_ONLY = ["a_fast_write", "a_outclr_en", "a_output_sel",
                      "b_fast_write", "b_outclr_en", "b_output_sel"]

_OPT_O_RE = re.compile(r"^o (\S+) (\S+)\s*$")
_M10K_S_RE = re.compile(r"^s (M10K\.\d+\.\d+):(\S+) (\S+)\s*$")
_GPIO_LINE_RE = re.compile(
    r"^s GPIO\.(\d+)\.(\d+):(\S+)\s+(\S+)\s*(?:;\s*(\S+))?\s*$")


def setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cyclonev_blockmux_fuzz")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_PATH)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def load_rows(dump_target: str, mux: str = None) -> list:
    """cv_block_muxes rows for a dump_target (and optionally one mux name)."""
    import db
    import schema
    from sqlalchemy import select
    t = schema.cv_block_muxes
    q = select(t).where(t.c.dump_target == dump_target)
    if mux is not None:
        q = q.where(t.c.mux == mux)
    with db.engine().connect() as conn:
        rows = conn.execute(q.order_by(t.c.id)).mappings().all()
    return [dict(r) for r in rows]


def load_mux_rows(dump_target: str, mux: str) -> list:
    """All cv_block_muxes rows for (dump_target, mux). Mux name is not unique
    on its own (drive_strength has an X and an x variant), so return all."""
    return load_rows(dump_target, mux)


def row_default(row):
    """Mistral's default for a row: the raw value (b/r) or the named/number
    value at default_value_idx (n/m).  None when the row has no default."""
    if row["stype"] in ("n", "m"):
        if row["default_value_idx"] is None or not row["values"]:
            return None
        return row["values"][row["default_value_idx"]][1]
    return row["default_value"]


def find_claim(rows: list, name: str):
    """(row, hex_mask, index) for the named value, or None."""
    for r in rows:
        if r["stype"] not in ("m", "n") or not r["values"]:
            continue
        for idx, (mask, val_name) in enumerate(r["values"]):
            if str(val_name) == name:
                return r, mask, idx
    return None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_")


def run(cmd, cwd, logger, timeout):
    """Returns (ok, combined_text). A timeout is logged with the limit and the
    command; the caller records it as INCONCLUSIVE, never as a pass."""
    logger.info("+ %s", " ".join(str(c) for c in cmd))
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error("TIMEOUT after %ds (limit): %s", timeout, " ".join(str(c) for c in cmd))
        return False, f"TIMEOUT after {timeout}s"
    text = res.stdout + res.stderr
    if res.returncode != 0:
        logger.error("FAILED rc=%d: %s", res.returncode, " ".join(str(c) for c in cmd))
        return False, text
    return True, text


def quartus_errors(text: str, limit: int = 3) -> str:
    errs = [ln.strip() for ln in text.splitlines() if re.search(r"\bError\b\s*\(", ln)]
    return " | ".join(errs[:limit]) if errs else "(no Error line in Quartus output)"


def qsf_header(top: str) -> list:
    return ['set_global_assignment -name FAMILY "Cyclone V"',
            f"set_global_assignment -name DEVICE {DEVICE}",
            f"set_global_assignment -name TOP_LEVEL_ENTITY {top}",
            f"set_global_assignment -name VERILOG_FILE {top}.v"]


def write_design(d: Path, top: str, assignments: list, pin: str):
    """GPIO design: one port `q` pinned to `pin`; `assignments` are per-pin
    (appended with `-to q`)."""
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{top}.v").write_text(
        f"module {top}(input d, output q);\n  assign q = d;\nendmodule\n")
    lines = qsf_header(top) + [f"set_location_assignment {pin} -to q"]
    lines += [f"{a} -to q" for a in assignments]
    (d / f"{top}.qsf").write_text("\n".join(lines) + "\n")
    (d / f"{top}.qpf").write_text(f'QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "{top}"\n')


def write_design_global(d: Path, top: str, global_assignments: list):
    """Opt design: the same one-pin design as the GPIO one, but the
    assignments are global (no `-to`)."""
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{top}.v").write_text(
        f"module {top}(input d, output q);\n  assign q = d;\nendmodule\n")
    lines = qsf_header(top) + [f"set_location_assignment {DEFAULT_PIN} -to q"]
    lines += [f"set_global_assignment -name {a}" for a in global_assignments]
    (d / f"{top}.qsf").write_text("\n".join(lines) + "\n")
    (d / f"{top}.qpf").write_text(f'QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "{top}"\n')


def write_design_ram(d: Path, top: str, verilog: str):
    """M10K design: no pins.  Unplaced ports are auto-assigned by the fitter."""
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{top}.v").write_text(verilog)
    (d / f"{top}.qsf").write_text("\n".join(qsf_header(top)) + "\n")
    (d / f"{top}.qpf").write_text(f'QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "{top}"\n')


def quartus_chain(top: str, d: Path, logger, fit_timeout: int = TIMEOUT_QUARTUS_FIT):
    """map -> fit -> asm -> cpf.  Returns error reason, or None on success."""
    ok, txt = run([str(QUARTUS_BIN / "quartus_map"), top, "--family=Cyclone V",
                   f"--part={DEVICE}"], d, logger, TIMEOUT_QUARTUS_FAST)
    if not ok:
        return f"quartus_map: {quartus_errors(txt)}"
    ok, txt = run([str(QUARTUS_BIN / "quartus_fit"), top], d, logger, fit_timeout)
    if not ok:
        return f"quartus_fit rejected the setting: {quartus_errors(txt)}"
    ok, txt = run([str(QUARTUS_BIN / "quartus_asm"), top], d, logger, TIMEOUT_QUARTUS_FAST)
    if not ok:
        return f"quartus_asm: {quartus_errors(txt)}"
    ok, txt = run([str(QUARTUS_BIN / "quartus_cpf"), "-c", f"{top}.sof", f"{top}.rbf"],
                  d, logger, TIMEOUT_QUARTUS_FAST)
    if not ok:
        return f"quartus_cpf: {quartus_errors(txt)}"
    return None


def mistral_decomp(top: str, d: Path, logger):
    """Returns (error_reason, bt_text)."""
    bt = d / f"{top}.bt"
    ok, _ = run([str(MISTRAL_CV), "decomp", DEVICE, f"{top}.rbf", f"{top}.bt"],
                d, logger, TIMEOUT_MISTRAL)
    if not ok or not bt.exists():
        return "mistral-cv decomp failed", ""
    return None, bt.read_text(errors="replace")


def asm_usercode(d: Path, top: str):
    """JTAG usercode from Quartus's own assembler report, or None."""
    rpt = d / f"{top}.asm.rpt"
    if not rpt.exists():
        return None
    m = re.search(r"JTAG usercode\s*;\s*0x([0-9A-Fa-f]+)", rpt.read_text(errors="replace"))
    return int(m.group(1), 16) if m else None


def rbf_diff_bytes(a: Path, b: Path) -> int:
    """Byte-level diff count of two .rbf files (same size expected).  0 means
    the Quartus setting did not change the bitstream."""
    x, y = a.read_bytes(), b.read_bytes()
    if len(x) != len(y):
        return max(len(x), len(y))
    return sum(1 for p, q in zip(x, y) if p != q)


# ── GPIO path (behaviour unchanged) ──────────────────────────────────────────

def quartus_knob(mux: str, name: str):
    """(assignments, None) or (None, reason). assignments is a list of
    (qsf_line_without_pin) strings applied to the target pin."""
    table = GPIO_KNOBS.get(mux)
    if table is None:
        return None, f"no Quartus knob mapped for gpio.{mux} (not attempted)"
    for rx, iostd in table:
        m = rx.match(name)
        if m:
            strength = f"{int(m.group(1))}mA"
            return ([f'set_instance_assignment -name IO_STANDARD "{iostd}"',
                     f'set_instance_assignment -name CURRENT_STRENGTH_NEW "{strength}"'],
                    None)
    return None, (f"value {name!r} has no single-knob IO_STANDARD/strength mapping "
                  f"(combined, OCT/termination, or programming-pad value)")


def pin_matches(bt_pin: str, pin: str) -> bool:
    """mistral prints the pad name in its own spelling; compare on the site
    token (e.g. 'F8') so 'PIN_F8' and 'F8' are the same pin."""
    norm = lambda s: s.upper().replace("PIN_", "").strip()
    return norm(bt_pin) == norm(pin)


def read_gpio_lines(bt_text: str, mux: str) -> list:
    """All `s GPIO.x.y:<mux>.<span> <name> ; <pin>` lines, as dicts.
    mistral-cv prints mux and value names UPPERCASE (DRIVE_STRENGTH.2
    V3P0_LVTTL_8MA); names are returned lowercased to match the DB."""
    out = []
    for line in bt_text.splitlines():
        m = _GPIO_LINE_RE.match(line.rstrip("\n"))
        if not m:
            continue
        field, name, pin = m.group(3), m.group(4), m.group(5)
        mm = re.match(rf"^{re.escape(mux)}(?:\.(\d+))?$", field, re.IGNORECASE)
        if not mm:
            continue
        out.append({"tile": f"GPIO.{m.group(1)}.{m.group(2)}",
                    "span": int(mm.group(1)) if mm.group(1) else None,
                    "name": name.lower(), "pin": pin})
    return out


def compile_and_decode(top: str, assignments: list, pin: str, logger):
    """Quartus chain + mistral decomp for a GPIO pin design. Returns
    (error_reason, target_lines, all_gpio_lines); error_reason is None on success."""
    d = WORK_DIR / top
    write_design(d, top, assignments, pin)
    logger.info("=== %s: %s -> %s ===", top, pin, "; ".join(assignments) or "(no assignments)")
    err = quartus_chain(top, d, logger)
    if err:
        return err, [], []
    err, bt_text = mistral_decomp(top, d, logger)
    if err:
        return err, [], []
    lines = read_gpio_lines(bt_text, MUX)
    target = [ln for ln in lines if pin_matches(ln["pin"], pin)]
    return None, target, lines


def fuzz_value(name: str, rows: list, pin: str, logger) -> dict:
    claim = find_claim(rows, name)
    if claim is None:
        return {"value": name, "verdict": "INCONCLUSIVE",
                "reason": f"{name!r} is not a named value of gpio.{MUX}"}
    row, mask, idx = claim
    result = {"value": name, "claimed_mask_hex": mask, "claimed_variant": row["variant"],
              "claimed_span_count": row["span"], "claimed_bcount": row["bcount"],
              "claimed_bit_positions_by_span": {str(s): b for s, b in enumerate(row["bits"])}}

    assignments, reason = quartus_knob(MUX, name)
    if assignments is None:
        logger.info("%s: INCONCLUSIVE -- %s", name, reason)
        return {**result, "verdict": "INCONCLUSIVE", "reason": reason}

    err, target, _ = compile_and_decode(slug(f"gpio_{MUX}_{name}_{pin}"), assignments, pin, logger)
    if err:
        return {**result, "verdict": "INCONCLUSIVE", "reason": err}
    result["decoded_lines_for_pin"] = target
    if not target:
        logger.info("%s: INCONCLUSIVE -- no decoded %s line for %s", name, MUX, pin)
        return {**result, "verdict": "INCONCLUSIVE",
                "reason": f"no decoded {MUX} line for {pin} in the .bt (pin not decoded)"}

    names = sorted({ln["name"] for ln in target})
    verdict = "MATCH" if name in names else "MISMATCH"
    logger.info("%s: %s -- requested %s, decoded %s", name, verdict, name, names)
    return {**result, "verdict": verdict, "decoded_names": names}


def control_default(pin: str, logger) -> dict:
    """No IO_STANDARD / CURRENT_STRENGTH assignment: what does the pin decode
    to by default? Needed to show a MATCH is not just the default coinciding."""
    err, target, _ = compile_and_decode(slug(f"gpio_{MUX}_control_default_{pin}"), [], pin, logger)
    if err:
        return {"verdict": "CONTROL_FAILED", "reason": err}
    names = sorted({ln["name"] for ln in target})
    logger.info("control (no strength assignment): %s decodes to %s", pin, names)
    return {"verdict": "CONTROL", "decoded_names": names,
            "decoded_lines_for_pin": target}


# ── opt path ─────────────────────────────────────────────────────────────────

def parse_opt(bt_text: str) -> dict:
    """{mux_name_lower: raw_printed_string} for every `o` line."""
    out = {}
    for line in bt_text.splitlines():
        m = _OPT_O_RE.match(line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def opt_observed(row: dict, printed: dict):
    """Raw value Mistral reports for this row: printed if present, else default."""
    if row["mux"] in printed:
        s = printed[row["mux"]]
        if row["stype"] == "r":
            return int(s.replace(".", ""), 16)   # wide values print as dot-separated 32-bit groups
        return int(s)
    d = row_default(row)
    if d is None:
        return None
    if row["stype"] == "r" and d == -1:
        return (1 << row["bcount"]) - 1
    return d


def opt_compile(top: str, qsf: list, logger):
    """Returns (err, bt_text, d, rbf_path)."""
    d = WORK_DIR / top
    write_design_global(d, top, qsf)
    logger.info("=== %s: %s ===", top, "; ".join(qsf) or "(default)")
    err = quartus_chain(top, d, logger)
    if err:
        return err, "", d
    err, bt_text = mistral_decomp(top, d, logger)
    return err, bt_text, d


def check_opt(mux: str, spec: dict, rows_by_mux: dict, base: dict, logger) -> dict:
    row = rows_by_mux[mux]
    base_rbf = base["d"] / f"{base['top']}.rbf"
    if spec.get("kind") == "usercode":
        top = slug(f"opt_{mux}_checksum_off")
    else:
        top = slug(f"opt_{mux}_knob")
    err, bt_text, d = opt_compile(top, spec["qsf"], logger)
    if err:
        return {"verdict": "INCONCLUSIVE", "reason": err, "qsf": spec["qsf"]}

    printed = parse_opt(bt_text)
    obs_knob = opt_observed(row, printed)
    obs_default = opt_observed(row, base["printed"])
    diff = rbf_diff_bytes(d / f"{top}.rbf", base_rbf)
    result = {"qsf": spec["qsf"], "observed_knob": obs_knob, "observed_default": obs_default,
              "rbf_bytes_differing_from_default": diff,
              "bits": row["bits"], "stype": row["stype"], "mistral_default": row_default(row)}
    # Every other opt row whose decoded value moved between the two builds.
    moved = {}
    for m, r in rows_by_mux.items():
        if r["stype"] not in ("b", "n", "r"):
            continue
        a, b = opt_observed(r, base["printed"]), opt_observed(r, printed)
        if a != b:
            moved[m] = {"default": a, "knob": b, "bits": r["bits"]}
    result["other_rows_moved"] = moved

    if spec.get("kind") == "usercode":
        asm_knob = asm_usercode(d, top)
        asm_default = asm_usercode(base["d"], base["top"])
        result.update({"asm_usercode_knob": asm_knob, "asm_usercode_default": asm_default})
        ok = asm_knob is not None and obs_knob == asm_knob and obs_default == asm_default
        result["verdict"] = "MATCH" if ok else "MISMATCH"
        result["reason"] = "Mistral jtag_id vs Quartus assembler JTAG usercode, both builds"
        return result

    if spec.get("knob") is None:
        result["verdict"] = "INCONCLUSIVE"
        result["reason"] = (f"knob applied (asm report) but no expectation; knob {spec['qsf']} "
                            f"left the printed bit at {obs_knob}")
        return result
    if diff == 0:
        result["verdict"] = "INCONCLUSIVE"
        result["reason"] = (f"Quartus accepted {spec['qsf']} but the .rbf is byte-identical to the "
                            "default build: the setting is not visible in the bitstream this flow "
                            "produces; Mistral's bit cannot be tested by this knob")
        return result
    knob_ok = obs_knob == spec["knob"]
    default_ok = obs_default == spec["default"]
    result["expected_knob"] = spec["knob"]
    result["expected_default"] = spec["default"]
    result["verdict"] = "MATCH" if (knob_ok and default_ok) else "MISMATCH"
    bits = []
    if not knob_ok:
        bits.append(f"knob build decodes {obs_knob}, name predicts {spec['knob']}")
    if not default_ok:
        bits.append(f"default build decodes {obs_default}, name predicts {spec['default']}")
    result["reason"] = "; ".join(bits) or "knob and default both as the name predicts"
    return result


def run_opt(names: list, logger) -> dict:
    rows = load_rows("opt")
    rows_by_mux = {r["mux"]: r for r in rows}
    # Shared default build: no assignments, gives the default raw bits and the reference rbf.
    err, bt_text, d = opt_compile(slug("opt_default_build"), [], logger)
    if err:
        sys.exit(f"default build failed: {err}")
    base = {"top": slug("opt_default_build"), "d": d, "printed": parse_opt(bt_text)}
    results = {}
    for mux in names:
        key = f"opt.{mux}"
        if mux in OPT_UNTESTED:
            results[key] = {"verdict": "INCONCLUSIVE", "reason": OPT_UNTESTED[mux]}
            continue
        if mux not in rows_by_mux:
            results[key] = {"verdict": "INCONCLUSIVE", "reason": f"no opt row named {mux!r}"}
            continue
        spec = OPT_KNOBS.get(mux)
        if spec is None:
            results[key] = {"verdict": "INCONCLUSIVE", "reason": "no knob mapped"}
            continue
        results[key] = check_opt(mux, spec, rows_by_mux, base, logger)
        logger.info("%s: %s -- %s", key, results[key]["verdict"], results[key].get("reason", ""))
    return results


# ── m10k path ────────────────────────────────────────────────────────────────

def m10k_verilog(style: str, w: int, top: str) -> str:
    d = M10K_DEPTH[w]
    a = max(1, math.ceil(math.log2(d)))
    ram = f'  (* ramstyle = "M10K" *) reg [{w-1}:0] mem [0:{d-1}];\n'
    if style == "sp":
        return (f"module {top}(input clk, input we, input [{a-1}:0] addr, input [{w-1}:0] din, "
                f"output reg [{w-1}:0] dout);\n" + ram +
                "  always @(posedge clk) begin\n    if (we) mem[addr] <= din;\n"
                "    dout <= mem[addr];\n  end\nendmodule\n")
    if style == "sdp":
        return (f"module {top}(input clk, input we, input [{a-1}:0] waddr, input [{a-1}:0] raddr, "
                f"input [{w-1}:0] din, output reg [{w-1}:0] dout);\n" + ram +
                "  always @(posedge clk) begin\n    if (we) mem[waddr] <= din;\n"
                "    dout <= mem[raddr];\n  end\nendmodule\n")
    if style == "tdpip":
        return (f"module {top}(input clk, input we_a, input we_b, input [{a-1}:0] addr_a, "
                f"input [{a-1}:0] addr_b, input [{w-1}:0] din_a, input [{w-1}:0] din_b, "
                f"output [{w-1}:0] q_a, output [{w-1}:0] q_b);\n"
                f"  altsyncram #(.operation_mode(\"BIDIR_DUAL_PORT\"), "
                f".width_a({w}), .widthad_a({a}), .numwords_a({d}), "
                f".width_b({w}), .widthad_b({a}), .numwords_b({d}), "
                f".outdata_reg_a(\"UNREGISTERED\"), .outdata_reg_b(\"UNREGISTERED\"), "
                f".address_reg_b(\"CLOCK1\"), .indata_reg_b(\"CLOCK1\"), "
                f".wrcontrol_wraddress_reg_b(\"CLOCK1\"), "
                f".read_during_write_mode_port_a(\"NEW_DATA_NO_NBE_READ\"), "
                f".read_during_write_mode_port_b(\"NEW_DATA_NO_NBE_READ\"), "
                f".power_up_uninitialized(\"FALSE\"), .intended_device_family(\"Cyclone V\"), "
                f".ram_block_type(\"M10K\"), .lpm_type(\"altsyncram\")) ram (\n"
                "    .clock0(clk), .clock1(clk), .address_a(addr_a), .address_b(addr_b), "
                ".data_a(din_a), .data_b(din_b), .wren_a(we_a), .wren_b(we_b), "
                ".q_a(q_a), .q_b(q_b), .aclr0(1'b0), .aclr1(1'b0), "
                ".addressstall_a(1'b0), .addressstall_b(1'b0), .byteena_a(1'b1), "
                ".byteena_b(1'b1), .clocken0(1'b1), .clocken1(1'b1), .clocken2(1'b1), "
                ".clocken3(1'b1), .rden_a(1'b1), .rden_b(1'b1));\nendmodule\n")
    if style == "tdp":
        return (f"module {top}(input clk, input we_a, input we_b, input [{a-1}:0] addr_a, "
                f"input [{a-1}:0] addr_b, input [{w-1}:0] din_a, input [{w-1}:0] din_b, "
                f"output reg [{w-1}:0] dout_a, output reg [{w-1}:0] dout_b);\n" + ram +
                "  always @(posedge clk) begin\n    if (we_a) mem[addr_a] <= din_a;\n"
                "    dout_a <= mem[addr_a];\n  end\n"
                "  always @(posedge clk) begin\n    if (we_b) mem[addr_b] <= din_b;\n"
                "    dout_b <= mem[addr_b];\n  end\nendmodule\n")
    raise ValueError(style)


def m10k_expected(style: str, w: int, mux: str):
    if mux == "true_dual_port":
        return 1 if style in ("tdp", "tdpip") else 0
    if mux in ("a_data_width", "b_data_width"):
        if style == "sp" and mux == "b_data_width":
            return None          # port B unused in single-port RAM: no expectation
        return w
    return None


def m10k_observed(rows_by_mux: dict, mux: str, tile_lines: dict, tile: str):
    """Raw value of `mux` on `tile`: printed if present, else Mistral's default."""
    row = rows_by_mux[mux]
    if mux in tile_lines.get(tile, {}):
        s = tile_lines[tile][mux]
        return int(s) if row["stype"] in ("n", "b") else s.lower()
    d = row_default(row)
    return d


def run_m10k(styles: list, logger) -> dict:
    rows = load_rows("m10k")
    rows_by_mux = {r["mux"]: r for r in rows}
    results = {}
    for style in styles:
        for w in M10K_WIDTHS:
            top = slug(f"m10k_{style}_w{w}")
            d = WORK_DIR / top
            write_design_ram(d, top, m10k_verilog(style, w, top))
            logger.info("=== %s: %s RAM, width %d, depth %d ===", top, style, w, M10K_DEPTH[w])
            fit_timeout = TIMEOUT_QUARTUS_FIT_TDP if style == "tdp" else TIMEOUT_QUARTUS_FIT
            err = quartus_chain(top, d, logger, fit_timeout)
            if err:
                for mux in M10K_CHECKED:
                    results[f"m10k.{style}.w{w}.{mux}"] = {
                        "verdict": "INCONCLUSIVE", "reason": err}
                continue
            err, bt_text = mistral_decomp(top, d, logger)
            if err:
                for mux in M10K_CHECKED:
                    results[f"m10k.{style}.w{w}.{mux}"] = {
                        "verdict": "INCONCLUSIVE", "reason": err}
                continue
            # tile -> {mux: printed value}, from `s M10K.x.y:<MUX> <value>` lines
            tile_lines = {}
            for line in bt_text.splitlines():
                m = _M10K_S_RE.match(line)
                if m:
                    tile_lines.setdefault(m.group(1), {})[m.group(2).lower()] = m.group(3)
            tiles = sorted(tile_lines)
            logger.info("%s: M10K tiles decoded: %s", top, tiles or "none")
            for mux in M10K_CHECKED + M10K_OBSERVED_ONLY:
                key = f"m10k.{style}.w{w}.{mux}"
                if mux not in rows_by_mux:
                    results[key] = {"verdict": "INCONCLUSIVE", "reason": f"no row {mux}"}
                    continue
                observed = {t: m10k_observed(rows_by_mux, mux, tile_lines, t) for t in tiles}
                entry = {"style": style, "width": w, "tiles": tiles,
                         "observed_by_tile": {t: observed[t] for t in tiles}}
                if not tiles:
                    results[key] = {**entry, "verdict": "INCONCLUSIVE",
                                    "reason": "no M10K tile in the decoded bitstream"}
                    continue
                if mux in M10K_OBSERVED_ONLY:
                    results[key] = {**entry, "verdict": "INCONCLUSIVE",
                                    "reason": "observed only: no Quartus knob maps to this mux"}
                    continue
                exp = m10k_expected(style, w, mux)
                if exp is None:
                    results[key] = {**entry, "verdict": "INCONCLUSIVE",
                                    "reason": "no expectation (port unused in this RAM style)"}
                    continue
                entry["expected"] = exp
                bad = {t: v for t, v in observed.items() if v != exp}
                verdict = "MISMATCH" if bad else "MATCH"
                results[key] = {**entry, "verdict": verdict,
                                "reason": f"tiles disagreeing: {bad}" if bad else ""}
                logger.info("%s: %s -- expected %s, observed %s", key, verdict, exp, observed)
    return results


# ── lab / mlab path ──────────────────────────────────────────────────────────
# Probes are small designs whose registers are pinned to one LAB with
# `set_location_assignment LAB_Xa_Yb` (LAB.a.b in the decode; verified on
# LAB_X10_Y10 and LAB_X20_Y20).  Wires marked keep are pinned too, so the
# LUT feeding a register lands in the same LAB where the fitter allows it.
# The fitter, not the probe, chooses the LUT slot: checks read the slot from
# the FF routing line (`r LAB.x.y.S:FFT0`), never from a fixed index.

LAB_PROBE_LAB = "LAB_X20_Y20"
LAB_PROBES = {
    # Control: one posedge FF, no clear/enable/sload, clock via the LAB input.
    "ctrl": ("module {t}(input clk, input d, output q);\n  reg a;\n"
             "  always @(posedge clk) a <= d;\n  assign q = a;\nendmodule\n",
             [("a", LAB_PROBE_LAB)]),
    "negclk": ("module {t}(input clk, input d, output q);\n  reg a;\n"
               "  always @(negedge clk) a <= d;\n  assign q = a;\nendmodule\n",
               [("a", LAB_PROBE_LAB)]),
    # Two clocks in one LAB: two FFs, two slots.
    "clk2": ("module {t}(input c0, input c1, input d, output q0, output q1);\n"
             "  reg a, b;\n  always @(posedge c0) a <= d;\n  always @(posedge c1) b <= d;\n"
             "  assign q0 = a;\n  assign q1 = b;\nendmodule\n",
             [("a", LAB_PROBE_LAB), ("b", LAB_PROBE_LAB)]),
    # Three clocks: no LAB pin (a LAB holding all three fails to fit, Error 170071).
    "clk3": ("module {t}(input c0, input c1, input c2, input d, output q0, output q1, output q2);\n"
             "  reg a, b, c;\n  always @(posedge c0) a <= d;\n  always @(posedge c1) b <= d;\n"
             "  always @(posedge c2) c <= d;\n  assign q0 = a;\n  assign q1 = b;\n"
             "  assign q2 = c;\nendmodule\n", []),
    # Synchronous clear / load / enable written as LUT logic (keep wire pinned).
    "sclr": ("module {t}(input clk, input rst, input d, output q);\n  reg a;\n"
             "  (* keep *) wire m = rst ? 1'b0 : d;\n  always @(posedge clk) a <= m;\n"
             "  assign q = a;\nendmodule\n",
             [("a", LAB_PROBE_LAB), ("m", LAB_PROBE_LAB)]),
    "sload": ("module {t}(input clk, input ld, input d, input x, output q);\n  reg a;\n"
              "  (* keep *) wire m = ld ? x : d;\n  always @(posedge clk) a <= m;\n"
              "  assign q = a;\nendmodule\n",
              [("a", LAB_PROBE_LAB), ("m", LAB_PROBE_LAB)]),
    "en": ("module {t}(input clk, input en, input d, output q);\n  reg a;\n"
           "  (* keep *) wire m = en ? d : a;\n  always @(posedge clk) a <= m;\n"
           "  assign q = a;\nendmodule\n",
           [("a", LAB_PROBE_LAB), ("m", LAB_PROBE_LAB)]),
    # Distributed RAM: 16x1 with ramstyle MLAB.  Fills every LUT slot of one MLAB.
    "mlab_ram": ("module {t}(input clk, input we, input [3:0] wa, input [3:0] ra, input d, "
                 "output q);\n  (* ramstyle = \"MLAB\" *) reg mem [0:15];\n  reg qq;\n"
                 "  always @(posedge clk) if (we) mem[wa] <= d;\n"
                 "  always @(posedge clk) qq <= mem[ra];\n  assign q = qq;\nendmodule\n",
                 []),
}

# ── LAB register banks (second pass) ─────────────────────────────────────────
# A bank is N registers on one clock, sharing an enable / clear / load.  Each
# bank k has its own inputs (e<k>, r<k>, l<k>), so two banks can differ.  The
# first pass used one register per probe, which left the shared controls as LUT
# logic; a bank of 16 gives the fitter a LAB-wide net to put on the dedicated line.
BANK_PROBE_SPECS = {
    "bank_plain": [dict(n=16)],                          # control: no shared control
    "bank_en": [dict(n=16, en=True)],
    "bank_aclr": [dict(n=16, clr="async")],
    "bank_sclr": [dict(n=16, clr="sync")],
    "bank_sload": [dict(n=16, load=True)],
    "bank_en2": [dict(n=10, en=True), dict(n=10, en=True)],      # two enables
    "bank_clr2": [dict(n=10, clr="async"), dict(n=10, clr="async")],  # two clears
    "bank_pn": [dict(n=10), dict(n=6, edge="neg")],      # posedge + negedge bank
}


def _bank_probe(banks: list):
    """(template, locs) for register banks pinned to LAB_PROBE_LAB."""
    ports, body, locs = ["input clk"], [], []
    for k, b in enumerate(banks):
        n = b["n"]
        edge = "negedge" if b.get("edge") == "neg" else "posedge"
        if b.get("en"):
            ports.append(f"input e{k}")
        if b.get("clr"):
            ports.append(f"input r{k}")
        if b.get("load"):
            ports += [f"input l{k}", f"input [{n-1}:0] x{k}"]
        ports += [f"input [{n-1}:0] d{k}", f"output [{n-1}:0] q{k}"]
        en = f"e{k}" if b.get("en") else "1'b1"
        for i in range(n):
            reg = f"b{k}_{i}"
            nxt = f"l{k} ? x{k}[{i}] : d{k}[{i}]" if b.get("load") else f"d{k}[{i}]"
            body.append(f"  reg {reg};")
            if b.get("clr") == "async":
                body.append(f"  always @({edge} clk or posedge r{k}) "
                            f"if (r{k}) {reg} <= 1'b0; else if ({en}) {reg} <= {nxt};")
            elif b.get("clr") == "sync":
                body.append(f"  always @({edge} clk) "
                            f"if (r{k}) {reg} <= 1'b0; else if ({en}) {reg} <= {nxt};")
            else:
                body.append(f"  always @({edge} clk) if ({en}) {reg} <= {nxt};")
            body.append(f"  assign q{k}[{i}] = {reg};")
            locs.append((reg, LAB_PROBE_LAB))
    tmpl = f"module {{t}}({', '.join(ports)});\n" + "\n".join(body) + "\nendmodule\n"
    return tmpl, locs


LAB_PROBES.update({name: _bank_probe(spec) for name, spec in BANK_PROBE_SPECS.items()})

# (target, probe, mux, span, kind, expected, basis).  span: None (g rows),
# "ff" (the slot holding the probe's FF), "ffall" (every slot with an FF), or an
# int.  kind:
#   eq       decoded == expected
#   moved    every checked span differs from the same span in bank_plain (control)
#   distinct two spans decode to different non-off values (expected unused)
#   observed recorded, INCONCLUSIVE (no independent expectation)
LAB_CHECKS = [
    # Control, no clear/enable/clock inversion requested.
    ("lab", "ctrl", "clk0_inv", None, "eq", 0,
     "no inversion requested: Mistral default 0"),
    ("lab", "ctrl", "en0_en", None, "eq", 0,
     "no register enable in the design: LAB enable 0 unused"),
    ("lab", "ctrl", "tsclr_dis", "ff", "eq", 1,
     "no synchronous clear in the design: top sclr disabled (1)"),
    ("lab", "clk2", "tclk_sel", "ff2", "distinct", None,
     "two FFs on two clocks in one LAB: two different LAB clock selects"),
    ("lab", "clk2", "tsclr_dis", "ff", "eq", 1,
     "no synchronous clear in the design: top sclr disabled (1)"),
    ("lab", "negclk", "clk0_sel", None, "observed", None,
     "negedge FF selects clkb; clka/clkb polarity not established by these probes"),
    ("lab", "ctrl", "clka_sel", None, "observed", None,
     "cin0 default in ctrl, din0 in clk2: source depends on fitter routing"),
    ("lab", "ctrl", "clkb_sel", None, "observed", None,
     "din1 in ctrl and negclk: unused clkb source, no fixed expectation"),
    ("lab", "ctrl", "aclr0_sel", None, "observed", None,
     "ACLR0 printed with no clear: value not discriminating"),
    ("lab", "ctrl", "tmode", "ff", "observed", None,
     "e_0 for a single top FF: mode meaning not established"),
    ("lab", "clk3", "tclk_sel", None, "observed", None,
     "clk2 not reached: a third clock lands in a different LAB"),
    ("lab", "sclr", "tsclr_dis", "ff", "observed", None,
     "sync clear is LUT logic in another LAB; top sclr stays 1 in this LAB"),
    ("lab", "sload", "sload_sel", None, "observed", None,
     "sload is LUT logic in another LAB; no LAB-level change"),
    ("lab", "en", "en0_en", None, "observed", None,
     "enable is LUT feedback (TDFF1L NLUT); LAB EN0 unchanged at 0"),
    ("mlab", "mlab_ram", "ram_dis", None, "eq", 0,
     "RAM in use: ram_dis must be 0 (enabled)"),
    ("mlab", "mlab_ram", "write_en", None, "eq", 1,
     "RAM with a write port: write_en 1"),
    ("mlab", "mlab_ram", "sclr_dis", None, "eq", 1,
     "RAM uses no synchronous clear: sclr disabled (1)"),
    ("mlab", "mlab_ram", "tmode", "all", "eq", "ram",
     "16x1 RAM fills all 10 LUT slots: each top mode RAM"),
    ("mlab", "mlab_ram", "bmode", "all", "eq", "ram",
     "16x1 RAM fills all 10 LUT slots: each bottom mode RAM"),
    ("mlab", "mlab_ram", "mcrg_voltage", None, "observed", None,
     "VCCL decoded; no independent voltage expectation"),
    ("mlab", "mlab_ram", "write_pulse_length", None, "observed", None,
     "650 decoded; no knob ties it to the design"),
    ("mlab", "mlab_ram", "clka_sel", None, "observed", None,
     "gin2 decoded; global-input mapping not established"),
    ("mlab", "mlab_ram", "tclk_sel", 5, "observed", None,
     "CLK2 decoded; clock-name mapping not established"),
    ("mlab", "mlab_ram", "t_feedback_sel", None, "observed", None,
     "all 10 slots print 1; no independent expectation"),
    ("mlab", "ctrl", "ram_dis", None, "eq", 1,
     "idle MLAB (control): ram_dis default 1"),
    ("mlab", "ctrl", "write_en", None, "eq", 0,
     "idle MLAB (control): write_en default 0"),
    # ── second pass: 16-FF banks sharing one control each (LAB-wide nets) ──
    ("lab", "bank_plain", "tsclr_dis", "fft", "eq", 1,
     "control bank: no sync clear, top sclr disabled (1) on every top-half FF slot"),
    ("lab", "bank_plain", "en0_en", None, "observed", None,
     "control bank: no shared enable"),
    ("lab", "bank_en", "en0_en", None, "moved", None,
     "shared clock enable on 16 FFs: LAB EN0 expected to leave its control value"),
    ("lab", "bank_en", "en0_ninv", None, "eq", 1,
     "enable not inverted: Mistral default 1"),
    ("lab", "bank_aclr", "aclr0_sel", None, "eq", "aclr0",
     "shared async clear on 16 FFs: clr0 source aclr0 (control also prints aclr0)"),
    ("lab", "bank_aclr", "aclr0_inv", None, "eq", 0,
     "active-high clear: no inversion, Mistral default 0"),
    ("lab", "bank_sclr", "tsclr_dis", "fft", "moved", None,
     "shared sync clear: top sclr on every top-half FF expected to leave control value 1"),
    ("lab", "bank_sclr", "bsclr_dis", "ffb", "moved", None,
     "shared sync clear: bottom sclr on every bottom-half FF expected to leave control value 1"),
    ("lab", "bank_sclr", "sclr_dis", None, "observed", None,
     "shared sync clear: LAB sclr_dis recorded"),
    ("lab", "bank_sload", "tsload_en", "fft", "moved", None,
     "shared sync load: top load enable on every top-half FF expected to leave control value 0"),
    ("lab", "bank_sload", "bsload_en", "ffb", "moved", None,
     "shared sync load: bottom load enable on every bottom-half FF expected to leave control value 0"),
    ("lab", "bank_sload", "sload_en", None, "observed", None,
     "shared sync load: LAB sload_en recorded (default 1)"),
    ("lab", "bank_en2", "en0_en", None, "moved", None,
     "bank A on enable 0: en0 expected to leave control value"),
    ("lab", "bank_en2", "en1_ninv", None, "eq", 1,
     "enable not inverted: Mistral default 1"),
    ("lab", "bank_clr2", "aclr0_sel", None, "eq", "aclr0",
     "bank A on async clear 0: clr0 source aclr0"),
    ("lab", "bank_clr2", "aclr1_sel", None, "eq", "aclr1",
     "bank B on async clear 1: clr1 source aclr1"),
    ("lab", "bank_clr2", "aclr0_inv", None, "moved", None,
     "bank A on async clear 0: ACLR0_INV expected to leave control value 0"),
    ("lab", "bank_clr2", "aclr1_inv", None, "moved", None,
     "bank B on async clear 1: ACLR1_INV expected to leave control value 0"),
    ("lab", "bank_plain", "clk0_inv", None, "observed", None,
     "16 posedge FFs, one clock: CLK0_INV recorded (ctrl single FF prints 1)"),
    ("lab", "bank_pn", "clk0_inv", None, "observed", None,
     "posedge bank and negedge bank in one LAB: CLK0_INV recorded"),
    ("lab", "bank_pn", "clk0_sel", None, "observed", None,
     "posedge bank and negedge bank in one LAB: CLK0_SEL recorded"),
    ("lab", "bank_pn", "tclk_sel", "fft", "observed", None,
     "top-half clock select per top FF slot, posedge and negedge banks"),
    ("lab", "bank_pn", "bclk_sel", "ffb", "observed", None,
     "bottom-half clock select per FF slot, posedge and negedge banks"),
]

_LABMUX_LINE_RE = re.compile(
    r"^s (M?LAB)\.(\d+)\.(\d+):([A-Za-z0-9_]+)(?:\.(\d+))? (\S+)")
_LABFF_LINE_RE = re.compile(r"^r (M?LAB)\.(\d+)\.(\d+)\.(\d+):FF(\w+)")


def parse_lab_decode(bt_text: str, kind: str):
    """kind 'LAB' or 'MLAB'.  Returns (printed, ff_slots, raw) where
    printed[tile][mux_lower][span_or_None] = printed value string,
    ff_slots[tile] = sorted slots with an FF routing line,
    raw[(tile, mux_lower, span)] = the .bt line."""
    printed, ff_slots, raw = {}, {}, {}
    for line in bt_text.splitlines():
        m = _LABMUX_LINE_RE.match(line)
        if m and m.group(1) == kind:
            tile = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            span = int(m.group(5)) if m.group(5) is not None else None
            key = (m.group(4).lower(), span)
            printed.setdefault(tile, {})[key] = m.group(6)
            raw[(tile, key[0], span)] = line
            continue
        m = _LABFF_LINE_RE.match(line)
        if m and m.group(1) == kind:
            tile = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            ff_slots.setdefault(tile, set()).add(int(m.group(4)))
    return printed, {t: sorted(s) for t, s in ff_slots.items()}, raw


CONTROL_PROBE = "bank_plain"     # reference build for kind "moved"


def _lab_spans(span_sel, ff: list, halves: dict) -> list:
    """Spans a check reads: None (g row), 'ff', 'ffall', 'fft'/'ffb' (top/bottom
    half FF slots only), 'all', or an int.  A top (`t`) row only applies to
    slots holding a top FF, so 'fft' is the span set for `t*` muxes."""
    if span_sel is None:
        return [None]
    if span_sel == "ff":
        return [ff[0]] if ff else []
    if span_sel == "ffall":
        return list(ff)
    if span_sel == "fft":
        return list(halves.get("T", []))
    if span_sel == "ffb":
        return list(halves.get("B", []))
    if span_sel == "all":
        return list(range(10))
    return [span_sel]


def parse_lab_halves(bt_text: str, kind: str) -> dict:
    """{tile: {'T': [slots], 'B': [slots]}} from `r LAB.x.y.S:FFT<n>` / `FFB<n>`
    routing lines.  T/B is the LAB half, which selects the t* or b* control set."""
    halves = {}
    for line in bt_text.splitlines():
        m = _LABFF_LINE_RE.match(line)
        if m and m.group(1) == kind:
            tile = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            h = halves.setdefault(tile, {"T": set(), "B": set()})
            h[m.group(5)[0]].add(int(m.group(4)))
    return {t: {k: sorted(v) for k, v in h.items()} for t, h in halves.items()}


def lab_norm(row, s):
    if s is None:
        return None
    if row["stype"] in ("b", "n"):
        return int(s)
    return s.lower()


def lab_observed(row, printed_tile: dict, mux: str, span):
    """Value for (mux, span) in this tile, printed or Mistral's default."""
    key = (mux, span)
    if key in printed_tile:
        return lab_norm(row, printed_tile[key]), True
    return row_default(row), False


def pick_tile(ff_slots: dict, printed: dict, kind: str, idle_ok: bool):
    """Tile holding the probe's FFs (most FF routing lines).  idle_ok: no FF
    needed, use the first MLAB tile without FFs (the MLAB control)."""
    cand = [(len(s), t) for t, s in ff_slots.items() if s]
    if cand:
        return max(cand)[1]
    if idle_ok:
        idle = sorted(t for t in printed if t.startswith(kind + "."))
        return idle[0] if idle else None
    return None


def compile_lab_probe(probe: str, logger):
    """Quartus + mistral decomp for one probe.  Returns (error, bt_text)."""
    body, locs = LAB_PROBES[probe]
    top = slug(f"labdump_{probe}")
    d = WORK_DIR / top
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{top}.v").write_text(body.format(t=top))
    lines = qsf_header(top) + [f"set_location_assignment {lab} -to {reg}" for reg, lab in locs]
    (d / f"{top}.qsf").write_text("\n".join(lines) + "\n")
    (d / f"{top}.qpf").write_text(f'QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "{top}"\n')
    logger.info("=== %s: probe %s ===", top, probe)
    err = quartus_chain(top, d, logger)
    if err:
        return err, ""
    return mistral_decomp(top, d, logger)


def run_lab_dumps(targets: list, logger) -> dict:
    """Compile each needed probe once, decode for each target, return results."""
    probes_needed = sorted({c[1] for c in LAB_CHECKS if c[0] in targets})
    bts = {}
    for probe in probes_needed:
        err, bt = compile_lab_probe(probe, logger)
        bts[probe] = (err, bt)
    results = {}
    for target in targets:
        results.update(_lab_results(target, bts, logger))
    return results


def _lab_results(target: str, bts: dict, logger) -> dict:
    kind = "LAB" if target == "lab" else "MLAB"
    rows = load_rows(target)
    rows_by_mux = {}
    for r in rows:
        rows_by_mux.setdefault(r["mux"], r)
    decodes = {}
    for probe, (err, bt) in bts.items():
        if err:
            decodes[probe] = {"error": err}
            continue
        printed, ff_slots, raw = parse_lab_decode(bt, kind)
        tile = pick_tile(ff_slots, printed, kind,
                         idle_ok=(kind == "MLAB" and probe == "ctrl"))
        decodes[probe] = {"printed": printed, "ff": ff_slots, "raw": raw, "tile": tile,
                          "halves": parse_lab_halves(bt, kind)}
        logger.info("%s probe %s: tile %s, FF slots %s", kind, probe, tile,
                    ff_slots.get(tile, []) if tile else None)

    results = {}
    for tgt, probe, mux, span_sel, kind_chk, expected, basis in LAB_CHECKS:
        if tgt != target:
            continue
        key = f"{target}.{mux}.{probe}" + ("" if span_sel is None else f".{span_sel}")
        dec = decodes.get(probe, {})
        row = rows_by_mux.get(mux)
        if "error" in dec or row is None:
            results[key] = {"verdict": "INCONCLUSIVE", "basis": basis,
                            "reason": dec.get("error", f"no row {mux!r}")}
            logger.info("%s: INCONCLUSIVE -- %s", key, results[key]["reason"])
            continue
        tile = dec["tile"]
        if tile is None:
            results[key] = {"verdict": "INCONCLUSIVE", "basis": basis,
                            "reason": f"no {kind} tile with the probe's FFs in the .bt"}
            logger.info("%s: INCONCLUSIVE -- %s", key, results[key]["reason"])
            continue
        ptile = dec["printed"].get(tile, {})
        ff = dec["ff"].get(tile, [])
        halves = dec["halves"].get(tile, {})
        base = {"probe": probe, "tile": tile, "basis": basis, "ff_slots": ff,
                "ff_halves": halves}

        if kind_chk == "observed":
            spans = _lab_spans(span_sel, ff, halves)
            obs = {str(s): lab_observed(row, ptile, mux, s)[0] for s in spans}
            results[key] = {**base, "verdict": "INCONCLUSIVE", "observed": obs,
                            "reason": "observed only: " + basis}
            logger.info("%s: INCONCLUSIVE (observed %s) -- %s", key, obs, basis)
            continue

        if kind_chk == "distinct":
            if len(ff) < 2:
                results[key] = {**base, "verdict": "INCONCLUSIVE",
                                "reason": f"fewer than two FF slots in {tile}: {ff}"}
                continue
            a, _ = lab_observed(row, ptile, mux, ff[0])
            b, _ = lab_observed(row, ptile, mux, ff[1])
            ok = a != b and a is not None and b is not None
            verdict = "MATCH" if ok else "MISMATCH"
            results[key] = {**base, "verdict": verdict, "decoded": {str(ff[0]): a, str(ff[1]): b},
                            "reason": "relational: distinct per-slot clock selects"}
            logger.info("%s: %s -- slots %s decode %s / %s", key, verdict, ff[:2], a, b)
            continue

        if kind_chk == "moved":
            ctl = decodes.get(CONTROL_PROBE, {})
            if "error" in ctl or ctl.get("tile") is None:
                results[key] = {**base, "verdict": "INCONCLUSIVE",
                                "reason": f"no control decode ({CONTROL_PROBE}) to compare"}
                logger.info("%s: INCONCLUSIVE -- no control decode", key)
                continue
            cprinted = ctl["printed"].get(ctl["tile"], {})
            spans = _lab_spans(span_sel, ff, halves)
            if not spans:
                results[key] = {**base, "verdict": "INCONCLUSIVE", "reason": "no FF slot to check"}
                continue
            moved = {}
            for s in spans:
                v, _ = lab_observed(row, ptile, mux, s)
                c, _ = lab_observed(row, cprinted, mux, s)
                moved[str(s)] = {"probe": v, "control": c}
            all_moved = all(x["probe"] != x["control"] for x in moved.values())
            verdict = "MATCH" if all_moved else "MISMATCH"
            results[key] = {**base, "verdict": verdict, "moved": moved, "control_tile": ctl["tile"],
                            "reason": ("moved vs control at every span" if all_moved else
                                       "did not move vs control at every span: " + basis)}
            logger.info("%s: %s -- %s", key, verdict, moved)
            continue

        # eq
        spans = _lab_spans(span_sel, ff, halves)
        if not spans:
            results[key] = {**base, "verdict": "INCONCLUSIVE", "reason": "no FF slot to check"}
            continue
        decoded = {}
        raw_lines = []
        for s in spans:
            v, _ = lab_observed(row, ptile, mux, s)
            decoded[str(s)] = v
            ln = dec["raw"].get((tile, mux, s))
            if ln:
                raw_lines.append(ln)
        bad = {s: v for s, v in decoded.items() if v != expected}
        verdict = "MISMATCH" if bad else "MATCH"
        results[key] = {**base, "verdict": verdict, "expected": expected, "decoded": decoded,
                        "raw": raw_lines,
                        "reason": (f"decoded {bad}, expected {expected}" if bad else basis)}
        logger.info("%s: %s -- expected %s, decoded %s", key, verdict, expected, decoded)

    # Row accounting: every cv_block_muxes row gets one verdict.
    row_results = {}
    for row in rows:
        mux = row["mux"]
        mine = [v for k, v in results.items() if k.startswith(f"{target}.{mux}.")]
        if any(v["verdict"] == "MISMATCH" for v in mine):
            vd = "MISMATCH"
        elif any(v["verdict"] == "MATCH" for v in mine):
            vd = "MATCH"
        else:
            vd = "INCONCLUSIVE"
        if mine:
            reason = "; ".join(sorted({v.get("reason", "") for v in mine}))
        elif mux == "lut_mask":
            reason = "LUT mask: exercised by the lifter, out of scope here"
        else:
            reason = "no probe reaches this mux"
        row_results[f"{target}.row.{row['subtype']}.{mux}"] = {
            "verdict": vd, "reason": reason, "subtype": row["subtype"], "stype": row["stype"]}
    results.update(row_results)
    return results


def print_row_counts(results: dict, target: str):
    rows = {k: v for k, v in results.items() if k.startswith(f"{target}.row.")}
    counts = {"MATCH": 0, "MISMATCH": 0, "INCONCLUSIVE": 0}
    for v in rows.values():
        counts[v["verdict"]] += 1
    print(f"{target}: {len(rows)} rows -- " + ", ".join(f"{k} {v}" for k, v in counts.items()))


# ── merge / main ─────────────────────────────────────────────────────────────

def merge_results(new: dict):
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    old = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    old.update(new)
    RESULTS_PATH.write_text(json.dumps(old, indent=2, sort_keys=True))


def print_gpio_list(rows):
    for r in rows:
        print(f"variant={r['variant']} span={r['span']} bcount={r['bcount']} "
              f"stype={r['stype']} values={len(r['values'] or [])}")
        for mask, nm in (r["values"] or []):
            _, reason = quartus_knob(MUX, str(nm))
            print(f"  {mask:>6}  {nm:32s} knob={'yes' if reason is None else 'no'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump-target", default="gpio", choices=["gpio", "opt", "m10k", "lab", "mlab"],
                    help="which cv_block_muxes dump target to check (default %(default)s)")
    ap.add_argument("--value", nargs="*", default=[],
                    help="gpio: named value(s) of drive_strength to test (one compile each)")
    ap.add_argument("--pin", default=DEFAULT_PIN, help="gpio: target pin (default %(default)s)")
    ap.add_argument("--list", action="store_true",
                    help="gpio: print the named values of the mux and whether each has a knob")
    ap.add_argument("--control", action="store_true",
                    help="gpio: also compile the pin with NO strength assignment")
    ap.add_argument("--all", action="store_true",
                    help="opt: every row (knobs + untested); m10k: every style x width")
    ap.add_argument("--m10k-style", nargs="*", default=M10K_STYLES, choices=M10K_STYLES,
                    help="m10k: restrict to these RAM styles (default all)")
    ap.add_argument("--opt-mux", nargs="*", default=[],
                    help="opt: specific row name(s) to check")
    args = ap.parse_args()

    if args.dump_target == "gpio":
        rows = load_mux_rows("gpio", MUX)
        if not rows:
            sys.exit("no cv_block_muxes rows for gpio.drive_strength -- run "
                     "scripts/cyclonev_db_import_blockmux.py first")
        if args.list:
            print_gpio_list(rows)
            return
        if not args.value and not args.control:
            ap.error("give at least one --value, or --control (or --list)")
        logger = setup_logging()
        logger.info("cyclonev_blockmux_fuzz: gpio.%s, pin %s, %d value(s), control=%s",
                    MUX, args.pin, len(args.value), args.control)
        results = {}
        if args.control:
            results[f"gpio.{MUX}.__control_default__"] = {
                "value": "__control_default__", **control_default(args.pin, logger)}
        pin_tag = "" if args.pin == DEFAULT_PIN else f"@{args.pin}"
        for name in args.value:
            results[f"gpio.{MUX}.{name}{pin_tag}"] = fuzz_value(name, rows, args.pin, logger)
        merge_results(results)
        print(f"\n=== gpio.{MUX} verdicts (pin {args.pin}) ===")
        for key, r in results.items():
            decoded = ",".join(r.get("decoded_names", [])) or "-"
            print(f"{r['verdict']:13s} {r['value']:24s} decoded={decoded:24s} {r.get('reason', '')}")
    elif args.dump_target == "opt":
        if not args.all and not args.opt_mux:
            ap.error("opt: give --all or --opt-mux NAME...")
        logger = setup_logging()
        names = sorted(set(OPT_KNOBS) | set(OPT_UNTESTED)) if args.all else args.opt_mux
        results = run_opt(names, logger)
        merge_results(results)
        print("\n=== opt verdicts ===")
        for key, r in results.items():
            print(f"{r['verdict']:13s} {key:44s} {r.get('reason', '')}")
    elif args.dump_target in ("lab", "mlab"):
        if not args.all:
            ap.error(f"{args.dump_target}: give --all")
        logger = setup_logging()
        results = run_lab_dumps([args.dump_target], logger)
        merge_results(results)
        print(f"\n=== {args.dump_target} verdicts (checks) ===")
        for key, r in results.items():
            if ".row." not in key:
                print(f"{r['verdict']:13s} {key:44s} {r.get('reason', '')}")
        print(f"\n=== {args.dump_target} row verdicts ===")
        print_row_counts(results, args.dump_target)
    else:
        if not args.all:
            ap.error("m10k: give --all")
        logger = setup_logging()
        results = run_m10k(args.m10k_style, logger)
        merge_results(results)
        print("\n=== m10k verdicts ===")
        for key, r in results.items():
            print(f"{r['verdict']:13s} {key:44s} {r.get('reason', '')}")
    print(f"\nresults: {RESULTS_PATH}")
    print(f"log: {LOG_PATH}")


if __name__ == "__main__":
    main()
