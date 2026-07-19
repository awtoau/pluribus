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


# A "found logic loop" that passes through a state element (latch/register) is
# not a true asynchronous combinational oscillator — it is a legitimate latch or
# registered feedback (e.g. a recovered GOWIN DL/DLC transparent latch whose D is
# computed from its own Q).  yosys's structural `check` reports it because a
# transparent latch has a D→Q path, but the state element breaks the loop
# functionally.  Only a loop with NO state element in it is a fatal comb loop.
_LOOP_HDR_PAT = re.compile(r"found logic loop in module")
_STATE_CELL_PAT = re.compile(
    r"\$(dff|dffe|adff|adffe|sdff|sdffe|dffsr|dlatch|adlatch|dlatchsr|sr)\b")


def classify_warnings(lines: list[str]) -> dict:
    no_driver = []
    conflicts = []
    comb_loops = []    # logic loops with no state element — fatal
    latch_loops = []   # logic loops broken by a latch/register — expected
    other = []

    n = len(lines)
    i = 0
    while i < n:
        ln = lines[i]
        if _LOOP_HDR_PAT.search(ln):
            # Gather the indented loop body (cells + wires) that follows.
            body = []
            j = i + 1
            while j < n and (lines[j].startswith((" ", "\t")) and lines[j].strip()):
                body.append(lines[j])
                j += 1
            if any(_STATE_CELL_PAT.search(b) for b in body):
                latch_loops.append(ln)
            else:
                comb_loops.append(ln)
            i = j
            continue
        if "Warning:" in ln:
            if any(p.search(ln) for p in _EXPECTED_PATTERNS):
                no_driver.append(ln)
            elif _CONFLICT_PAT.search(ln):
                conflicts.append(ln)
            else:
                other.append(ln)
        i += 1

    return {"no_driver": no_driver, "conflicts": conflicts,
            "comb_loops": comb_loops, "latch_loops": latch_loops,
            "other": other}


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
    # Match "ERROR:" anywhere in the line — yosys prefixes parse errors with the
    # source location (`file.v:NN: ERROR: …`), so a startswith check misses them
    # and silently passes a netlist yosys could not even elaborate.
    errors = [l for l in lines if "ERROR:" in l]

    print(f"  no-driver (expected) : {len(w['no_driver'])}")
    print(f"  conflicting-driver   : {len(w['conflicts'])}")
    print(f"  latch/reg loops (exp): {len(w['latch_loops'])}")
    print(f"  combinational loops  : {len(w['comb_loops'])}")
    print(f"  other warnings       : {len(w['other'])}")
    print(f"  errors               : {len(errors)}")

    if w["conflicts"]:
        print("\nConflicting-driver warnings (pad loopback):")
        for ln in w["conflicts"]:
            net = _CONFLICT_PAT.search(ln)
            print(f"  {net.group(1) if net else ln.strip()}")

    if w["comb_loops"]:
        print("\nCombinational loops (no state element — structural issue):")
        for ln in w["comb_loops"]:
            print(f"  {ln.strip()}")

    if w["other"]:
        print("\nUnexpected warnings:")
        for ln in w["other"]:
            print(f"  {ln.strip()}")

    if errors:
        print("\nErrors:")
        for ln in errors:
            print(f"  {ln.strip()}")

    # A nonzero yosys exit (parse/elaboration failure) is always fatal, as is a
    # true combinational loop or any unexpected warning.  Loops broken by a latch
    # or register are expected for a recovered netlist (see classify_warnings).
    fatal = bool(errors) or bool(w["other"]) or bool(w["comb_loops"]) or rc != 0
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
        if w["latch_loops"]:
            extras.append(f"{len(w['latch_loops'])} latch/reg feedback loops")
        if lec_diverged:
            extras.append("LEC diverged (non-fatal)")
        if extras:
            status += " (" + ", ".join(extras) + ")"
        print(f"\n{status}")
        sys.exit(0)


if __name__ == "__main__":
    main()
