#!/usr/bin/env python3
"""Fuzz ONE named Cyclone V block-mux value against real Quartus compiles
(issue #103: independent verification of Mistral's cv_block_muxes claims).

Mistral's `values` table says: named value N of mux M is the bit pattern V
(hex) at positions bits[span][0..bcount). mistral-cv decomp decodes an `m`
mux by exact-matching those bits against the table and printing the NAME.
This script builds a minimal Quartus design that Quartus is asked to put a
known named value into, decompiles it, and checks the decoded name for the
target pin.  Verdicts:

  MATCH        decoded name for the target pin == the requested name
  MISMATCH     pin decoded to a different name (or no table entry matched)
  INCONCLUSIVE no Quartus knob mapped for the value, Quartus rejected the
               setting, or the pin produced no decoded line at all

Limit (stated, not hidden): `mistral-cv decomp` does not print raw PRAM bits
for `m` muxes, only the decoded name, so a MATCH verifies that the bits at
cv_block_muxes.bits equal the claimed mask via Mistral's exact-match lookup,
not the raw bit values by themselves.  The span/position data used is printed
with every verdict so it can be checked by hand against the .bt.

Scope: GPIO (dump_target='gpio') drive_strength only, for now -- the knob is
the pin's IO standard + CURRENT_STRENGTH_NEW.  Other GPIO muxes are reported
INCONCLUSIVE with the reason (see KNOBS / docs/cyclonev-blockmux-fuzz-status.md).

Flow (same proven chain as cyclonev_dsp_fuzz.py):
    quartus_map -> quartus_fit -> quartus_asm -> quartus_cpf -c (.rbf)
    -> mistral-cv decomp -> read `s GPIO.*:<mux>.<span> <name> ; <pin>`

Device: 5CEBA4U19C8 (U19 = 484-pin package; pin names checked against the
Quartus IBIS package file 5ceba4_u4840.xml).

Usage:
    python3 scripts/cyclonev_blockmux_fuzz.py --value v3p0_lvttl_8ma
    python3 scripts/cyclonev_blockmux_fuzz.py --value v3p0_lvttl_8ma v1p8_2ma
    python3 scripts/cyclonev_blockmux_fuzz.py --list          # knob coverage

Output:
    tmp/logs/cyclonev_blockmux_fuzz.log        -- full run log
    tmp/cyclonev_blockmux_fuzz/<slug>/         -- qsf/v/rbf/bt per value
    tmp/cyclonev_blockmux_fuzz/results.json    -- verdict per value (merged)
Exit code: 0 when every requested value got a verdict, 2 on usage error.
A MISMATCH is a finding recorded in results.json, not a script failure.
"""
import argparse
import json
import logging
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
DUMP_TARGET = "gpio"
MUX = "drive_strength"
DEFAULT_PIN = "PIN_F8"          # bank 8A user I/O, single-ended (IBIS u4840)
WORK_DIR = REPO / "tmp" / "cyclonev_blockmux_fuzz"
LOG_PATH = REPO / "tmp" / "logs" / "cyclonev_blockmux_fuzz.log"
RESULTS_PATH = WORK_DIR / "results.json"

# Overall limits = 3x the measured worst case of a one-pin design on this host
# (quartus_fit ~10s, quartus_asm ~10s, quartus_map ~4s, cpf <1s, mistral-cv
# decomp ~1.5s; runs in docs/cyclonev-blockmux-fuzz-status.md). Expiry is
# logged with the limit and the command, and the value is INCONCLUSIVE.
TIMEOUT_QUARTUS_FAST = 30
TIMEOUT_QUARTUS_FIT = 60
TIMEOUT_MISTRAL = 15

# ── knob map: named value -> Quartus assignments ─────────────────────────────
# Each entry: regex on the value name -> (IO_STANDARD, strength-suffix).
# Only single-knob names are mapped. The IO_STANDARD strings are Quartus's
# own display names; a name Quartus rejects is recorded INCONCLUSIVE with the
# Quartus error text (never silently coerced to a neighbouring standard).
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

KNOBS = {
    "drive_strength": _LVCMOS_TTL_KNOBS + _SSTL_HSTL_KNOBS,
}


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


def load_mux_rows(dump_target: str, mux: str) -> list:
    """All cv_block_muxes rows for (dump_target, mux). Mux name is not unique
    on its own (drive_strength has an X and an x variant), so return all."""
    import db
    import schema
    from sqlalchemy import select
    t = schema.cv_block_muxes
    with db.engine().connect() as conn:
        rows = conn.execute(
            select(t).where(t.c.dump_target == dump_target, t.c.mux == mux)
            .order_by(t.c.id)
        ).mappings().all()
    return [dict(r) for r in rows]


def find_claim(rows: list, name: str):
    """(row, hex_mask, index) for the named value, or None."""
    for r in rows:
        if r["stype"] not in ("m", "n") or not r["values"]:
            continue
        for idx, (mask, val_name) in enumerate(r["values"]):
            if str(val_name) == name:
                return r, mask, idx
    return None


def quartus_knob(mux: str, name: str):
    """(assignments, None) or (None, reason). assignments is a list of
    (qsf_line_without_pin) strings applied to the target pin."""
    table = KNOBS.get(mux)
    if table is None:
        return None, f"no Quartus knob mapped for {DUMP_TARGET}.{mux} (not attempted)"
    for rx, iostd in table:
        m = rx.match(name)
        if m:
            strength = f"{int(m.group(1))}mA"
            return ([f'set_instance_assignment -name IO_STANDARD "{iostd}"',
                     f'set_instance_assignment -name CURRENT_STRENGTH_NEW "{strength}"'],
                    None)
    return None, (f"value {name!r} has no single-knob IO_STANDARD/strength mapping "
                  f"(combined, OCT/termination, or programming-pad value)")


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


def write_design(d: Path, top: str, assignments: list, pin: str):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{top}.v").write_text(
        f"module {top}(input d, output q);\n  assign q = d;\nendmodule\n")
    lines = [
        'set_global_assignment -name FAMILY "Cyclone V"',
        f"set_global_assignment -name DEVICE {DEVICE}",
        f"set_global_assignment -name TOP_LEVEL_ENTITY {top}",
        f"set_global_assignment -name VERILOG_FILE {top}.v",
        f"set_location_assignment {pin} -to q",
    ]
    lines += [f"{a} -to q" for a in assignments]
    (d / f"{top}.qsf").write_text("\n".join(lines) + "\n")
    (d / f"{top}.qpf").write_text(f'QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "{top}"\n')


def pin_matches(bt_pin: str, pin: str) -> bool:
    """mistral prints the pad name in its own spelling; compare on the site
    token (e.g. 'F8') so 'PIN_F8' and 'F8' are the same pin."""
    norm = lambda s: s.upper().replace("PIN_", "").strip()
    return norm(bt_pin) == norm(pin)


_GPIO_LINE_RE = re.compile(
    r"^s GPIO\.(\d+)\.(\d+):(\S+)\s+(\S+)\s*(?:;\s*(\S+))?\s*$")


def read_gpio_lines(bt: Path, mux: str) -> list:
    """All `s GPIO.x.y:<mux>.<span> <name> ; <pin>` lines, as dicts.
    mistral-cv prints mux and value names UPPERCASE (DRIVE_STRENGTH.2
    V3P0_LVTTL_8MA); names are returned lowercased to match the DB."""
    out = []
    with bt.open(errors="replace") as f:
        for line in f:
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
    """Quartus chain + mistral decomp. Returns (error_reason, target_lines,
    all_gpio_lines); error_reason is None on success."""
    d = WORK_DIR / top
    write_design(d, top, assignments, pin)
    logger.info("=== %s: %s -> %s ===", top, pin, "; ".join(assignments) or "(no assignments)")

    ok, txt = run([str(QUARTUS_BIN / "quartus_map"), top, "--family=Cyclone V",
                   f"--part={DEVICE}"], d, logger, TIMEOUT_QUARTUS_FAST)
    if not ok:
        return f"quartus_map: {quartus_errors(txt)}", [], []
    ok, txt = run([str(QUARTUS_BIN / "quartus_fit"), top], d, logger, TIMEOUT_QUARTUS_FIT)
    if not ok:
        return f"quartus_fit rejected the setting: {quartus_errors(txt)}", [], []
    ok, txt = run([str(QUARTUS_BIN / "quartus_asm"), top], d, logger, TIMEOUT_QUARTUS_FAST)
    if not ok:
        return f"quartus_asm: {quartus_errors(txt)}", [], []
    ok, txt = run([str(QUARTUS_BIN / "quartus_cpf"), "-c", f"{top}.sof", f"{top}.rbf"],
                  d, logger, TIMEOUT_QUARTUS_FAST)
    if not ok:
        return f"quartus_cpf: {quartus_errors(txt)}", [], []

    bt = d / f"{top}.bt"
    ok, txt = run([str(MISTRAL_CV), "decomp", DEVICE, f"{top}.rbf", f"{top}.bt"],
                  d, logger, TIMEOUT_MISTRAL)
    if not ok or not bt.exists():
        return "mistral-cv decomp failed", [], []
    lines = read_gpio_lines(bt, MUX)
    target = [ln for ln in lines if pin_matches(ln["pin"], pin)]
    return None, target, lines


def fuzz_value(name: str, row_info, pin: str, logger) -> dict:
    rows = row_info["rows"]
    claim = find_claim(rows, name)
    if claim is None:
        return {"value": name, "verdict": "INCONCLUSIVE",
                "reason": f"{name!r} is not a named value of {DUMP_TARGET}.{MUX}"}
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


def merge_results(new: dict):
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    old = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    old.update(new)
    RESULTS_PATH.write_text(json.dumps(old, indent=2, sort_keys=True))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--value", nargs="*", default=[],
                    help="named value(s) of gpio.drive_strength to test (one compile each)")
    ap.add_argument("--pin", default=DEFAULT_PIN, help="target pin (default %(default)s)")
    ap.add_argument("--list", action="store_true",
                    help="print the named values of the mux and whether each has a knob")
    ap.add_argument("--control", action="store_true",
                    help="also compile the pin with NO strength assignment and record "
                         "what it decodes to (default-coincidence check)")
    args = ap.parse_args()

    rows = load_mux_rows(DUMP_TARGET, MUX)
    if not rows:
        sys.exit(f"no cv_block_muxes rows for {DUMP_TARGET}.{MUX} -- run "
                 "scripts/cyclonev_db_import_blockmux.py first")
    row_info = {"rows": rows}

    if args.list:
        for r in rows:
            print(f"variant={r['variant']} span={r['span']} bcount={r['bcount']} "
                  f"stype={r['stype']} values={len(r['values'] or [])}")
            for mask, nm in (r["values"] or []):
                _, reason = quartus_knob(MUX, str(nm))
                print(f"  {mask:>6}  {nm:32s} knob={'yes' if reason is None else 'no'}")
        return

    if not args.value and not args.control:
        ap.error("give at least one --value, or --control (or --list)")

    logger = setup_logging()
    logger.info("cyclonev_blockmux_fuzz: %s.%s, pin %s, %d value(s), control=%s",
                DUMP_TARGET, MUX, args.pin, len(args.value), args.control)
    results = {}
    if args.control:
        results[f"{DUMP_TARGET}.{MUX}.__control_default__"] = {
            "value": "__control_default__", **control_default(args.pin, logger)}
    pin_tag = "" if args.pin == DEFAULT_PIN else f"@{args.pin}"
    for name in args.value:
        results[f"{DUMP_TARGET}.{MUX}.{name}{pin_tag}"] = fuzz_value(name, row_info, args.pin, logger)
    merge_results(results)

    print(f"\n=== {DUMP_TARGET}.{MUX} verdicts (pin {args.pin}) ===")
    for key, r in results.items():
        decoded = ",".join(r.get("decoded_names", [])) or "-"
        extra = r.get("reason", "")
        print(f"{r['verdict']:13s} {r['value']:24s} decoded={decoded:24s} {extra}")
    print(f"\nresults: {RESULTS_PATH}")
    print(f"log: {LOG_PATH}")


if __name__ == "__main__":
    main()
