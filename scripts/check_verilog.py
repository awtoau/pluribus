#!/usr/bin/env python3
"""Verilog lint and synthesis check for Pluribus-generated netlists.

Runs Yosys on a recovered .v file and categorises warnings:
  - "no driver" on port nets  → expected (input pads driven externally)
  - "conflicting driver"      → structural issue in recovery (report)
  - anything else             → unexpected (fail)

Exit 0 if only expected warnings; exit 1 on unexpected issues.

With --lec BASELINE it additionally runs a sequential-equivalence proof
(yosys equiv_induct) between the checked file and BASELINE — the regression
gate used to prove an emitter change is logic-preserving.  The recovered
netlist has no original RTL to check against, so the meaningful baseline is a
PRIOR emission of the same label.  Divergence is reported but non-fatal by
default (a DB change legitimately alters logic); --strict-lec makes it fatal.

Usage:
  python3 scripts/check_verilog.py tmp/<label>.v
  python3 scripts/check_verilog.py tmp/<label>.v --top top --strict
  python3 scripts/check_verilog.py tmp/<label>.v --out tmp/check_<label>.log
  python3 scripts/check_verilog.py out/<label>.v --top aw2 --lec prev.v
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


def run_yosys_lec(new_v: str, baseline_v: str, top: str) -> tuple[bool, list[str]]:
    """Sequential equivalence (equiv_induct) of new_v against baseline_v.

    Returns (equivalent, output_lines).  equivalent is True iff every $equiv
    cell is proven and none are unproven.  Declaration/comment-only emitter
    changes must come back equivalent; a real logic change comes back diverged.
    """
    script = (
        f"read_verilog -sv {baseline_v}; hierarchy -top {top}; "
        f"proc; flatten; opt_clean; rename {top} gold; design -stash gold; "
        f"read_verilog -sv {new_v}; hierarchy -top {top}; "
        f"proc; flatten; opt_clean; rename {top} gate; design -stash gate; "
        f"design -copy-from gold -as gold gold; "
        f"design -copy-from gate -as gate gate; "
        f"equiv_make gold gate equiv; hierarchy -top equiv; "
        f"equiv_induct; equiv_status"
    )
    result = subprocess.run(["yosys", "-p", script], capture_output=True, text=True)
    lines = (result.stdout + result.stderr).splitlines()
    proven = unproven = None
    for ln in lines:
        m = re.search(r"(\d+)\s+are proven and\s+(\d+)\s+are unproven", ln)
        if m:
            proven, unproven = int(m.group(1)), int(m.group(2))
    # yosys nonzero exit (e.g. a read/parse error) is never "equivalent".
    equivalent = (result.returncode == 0 and unproven == 0
                  and proven is not None and proven > 0)
    return equivalent, lines


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
    ap.add_argument("--lec", metavar="BASELINE",
                    help="also prove sequential equivalence vs this prior .v "
                         "(equiv_induct); reports divergence, non-fatal by default")
    ap.add_argument("--strict-lec", action="store_true",
                    help="with --lec, treat divergence from the baseline as a failure")
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

    # Optional sequential-equivalence regression gate vs a prior emission.
    lec_diverged = False
    if args.lec:
        if not Path(args.lec).exists():
            print(f"\nLEC: baseline {args.lec} not found — skipping equivalence check")
        else:
            print(f"\nLEC: proving equivalence vs {args.lec} (equiv_induct) …")
            equivalent, lec_lines = run_yosys_lec(str(vpath), args.lec, args.top)
            if args.out:
                Path(args.out).write_text(
                    Path(args.out).read_text() + "\n=== LEC ===\n"
                    + "\n".join(lec_lines) + "\n")
            proof = next((l.strip() for l in lec_lines if "are proven and" in l), "")
            if equivalent:
                print(f"  EQUIVALENT — {proof}")
            else:
                lec_diverged = True
                print(f"  DIVERGED from baseline — {proof or 'see log'}")
                print("  (expected if the DB/netlist changed; a logic change since "
                      "the last emission)")
    if args.strict_lec:
        fatal = fatal or lec_diverged

    if fatal:
        print("\nFAIL — unexpected issues found")
        sys.exit(1)
    else:
        status = "PASS"
        extras = []
        if w["conflicts"]:
            extras.append("pad-loopback warnings")
        if lec_diverged:
            extras.append("LEC diverged (non-fatal)")
        if extras:
            status += " (" + ", ".join(extras) + ")"
        print(f"\n{status}")
        sys.exit(0)


if __name__ == "__main__":
    main()
