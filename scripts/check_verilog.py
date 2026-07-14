#!/usr/bin/env python3
"""Verilog lint and synthesis check for Pluribus-generated netlists.

Runs Yosys on a recovered .v file and categorises warnings:
  - "no driver" on port nets  → expected (input pads driven externally)
  - "conflicting driver"      → structural issue in recovery (report)
  - anything else             → unexpected (fail)

Exit 0 if only expected warnings; exit 1 on unexpected issues.

Usage:
  python3 scripts/check_verilog.py tmp/<label>.v
  python3 scripts/check_verilog.py tmp/<label>.v --top top --strict
  python3 scripts/check_verilog.py tmp/<label>.v --out tmp/check_<label>.log
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

# Warnings that are structurally expected for a recovered FPGA netlist:
#   - Port inputs have no fabric driver (driven from board, not from fabric)
#   - Pad loopback conflicts where a LUT output feeds the same net as a pad
_EXPECTED_PATTERNS = [
    re.compile(r"Wire .+\b(is used but has no driver)\b"),
]

# Conflict warnings on pad nets are expected due to pad loopback arcs
# (a pad net can be simultaneously an input pad and an inverter output).
# Yosys names these two ways:
#   escaped identifier  → "multiple conflicting drivers for top.\PAD_NET:"
#   internal $cell name → "multiple conflicting drivers for top.$not$…_Y:"
# Match both with a broad capture of everything after "for ".
_CONFLICT_PAT = re.compile(r"multiple conflicting drivers for (.+)")


def run_yosys(verilog_path: str, top: str) -> tuple[int, list[str]]:
    """Run Yosys read+hierarchy+proc+check. Returns (returncode, output_lines)."""
    script = (
        f"read_verilog -sv {verilog_path}; "
        f"hierarchy -check -top {top}; "
        f"proc; "
        f"check"
    )
    result = subprocess.run(
        ["yosys", "-p", script],
        capture_output=True,
        text=True,
    )
    lines = (result.stdout + result.stderr).splitlines()
    return result.returncode, lines


def classify_warnings(lines: list[str]) -> dict:
    no_driver = []
    conflicts = []
    other = []

    for ln in lines:
        if "Warning:" not in ln:
            continue
        if any(p.search(ln) for p in _EXPECTED_PATTERNS):
            no_driver.append(ln)
        elif _CONFLICT_PAT.search(ln):
            conflicts.append(ln)
        else:
            other.append(ln)

    return {"no_driver": no_driver, "conflicts": conflicts, "other": other}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("verilog", help="Path to .v file to check")
    ap.add_argument("--top", default="top", help="Top module name (default: top)")
    ap.add_argument("--strict", action="store_true",
                    help="Treat pad-loopback conflict warnings as failures")
    ap.add_argument("--out", help="Write full Yosys log to this path")
    args = ap.parse_args()

    vpath = Path(args.verilog).resolve()
    if not vpath.exists():
        print(f"ERROR: {vpath} not found", file=sys.stderr)
        sys.exit(2)

    print(f"Checking {vpath.name} (top={args.top}) …")
    rc, lines = run_yosys(str(vpath), args.top)

    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n")
        print(f"  Full log → {args.out}")

    w = classify_warnings(lines)
    errors = [l for l in lines if l.strip().startswith("ERROR:")]

    print(f"  no-driver (expected) : {len(w['no_driver'])}")
    print(f"  conflicting-driver   : {len(w['conflicts'])}")
    print(f"  other warnings       : {len(w['other'])}")
    print(f"  errors               : {len(errors)}")

    if w["conflicts"]:
        print("\nConflicting-driver warnings (pad loopback):")
        for ln in w["conflicts"]:
            net = _CONFLICT_PAT.search(ln)
            print(f"  {net.group(1) if net else ln.strip()}")

    if w["other"]:
        print("\nUnexpected warnings:")
        for ln in w["other"]:
            print(f"  {ln.strip()}")

    if errors:
        print("\nErrors:")
        for ln in errors:
            print(f"  {ln.strip()}")

    fatal = bool(errors) or bool(w["other"])
    if args.strict:
        fatal = fatal or bool(w["conflicts"])

    if fatal:
        print("\nFAIL — unexpected issues found")
        sys.exit(1)
    else:
        status = "PASS"
        if w["conflicts"]:
            status += " (with pad-loopback warnings)"
        print(f"\n{status}")
        sys.exit(0)


if __name__ == "__main__":
    main()
