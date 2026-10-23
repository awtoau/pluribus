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
    ap.add_argument("--dump-target", default="gpio", choices=["gpio", "opt", "m10k"],
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
