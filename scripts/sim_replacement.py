#!/usr/bin/env python3
"""Simulate a replacement RTL design with pluribus tooling.

The replacement candidates (clean reimplementations of a recovered design)
live in their device RE project; pluribus provides the sim/verify harness.
This compiles a replacement RTL + its testbench with iverilog and runs it,
capturing the self-check verdict.

    python3 scripts/sim_replacement.py \
        --rtl /mnt/2tb/git/awto-2000/fpga/replacement/aw2_scope.v \
        --tb  /mnt/2tb/git/awto-2000/fpga/replacement/aw2_scope_tb.v \
        --top aw2_scope_tb

Defaults point at CAND-A (the aw2 scope faithful mirror).  Output +
verdict go to tmp/sim_replacement.log (and a VCD next to the vvp).
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(REPO, "tmp")

# CAND-A default (device RE project owns the RTL; pluribus owns the sim)
DEF_DIR = "/mnt/2tb/git/awto-2000/fpga/replacement"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rtl", default=os.path.join(DEF_DIR, "aw2_scope.v"),
                    help="replacement RTL source (default: CAND-A aw2_scope.v)")
    ap.add_argument("--tb", default=os.path.join(DEF_DIR, "aw2_scope_tb.v"),
                    help="testbench (default: aw2_scope_tb.v)")
    ap.add_argument("--top", default="aw2_scope_tb", help="testbench top module")
    ap.add_argument("--timeout", type=int, default=120,
                    help="vvp wall-clock guard (s); the design has its own "
                         "$finish — this only catches a hung compile/run")
    args = ap.parse_args()

    os.makedirs(TMP, exist_ok=True)
    log_path = os.path.join(TMP, "sim_replacement.log")
    vvp = os.path.join(TMP, "replacement.vvp")

    for f in (args.rtl, args.tb):
        if not os.path.exists(f):
            sys.exit(f"missing source: {f}")

    def tee(fh, *msg):
        line = " ".join(str(m) for m in msg)
        print(line, flush=True)
        fh.write(line + "\n")

    with open(log_path, "w") as fh:
        tee(fh, f"[sim] RTL {args.rtl}")
        tee(fh, f"[sim] TB  {args.tb}")

        # compile
        cc = subprocess.run(
            ["iverilog", "-g2012", "-Wall", "-o", vvp, "-s", args.top,
             args.rtl, args.tb],
            capture_output=True, text=True)
        for ln in (cc.stdout + cc.stderr).splitlines():
            tee(fh, "  [iverilog]", ln)
        if cc.returncode != 0:
            tee(fh, "[sim] COMPILE FAILED")
            sys.exit(1)

        # run (cwd=TMP so the VCD lands there)
        try:
            rr = subprocess.run(["vvp", os.path.basename(vvp)], cwd=TMP,
                                capture_output=True, text=True,
                                timeout=args.timeout)
        except subprocess.TimeoutExpired:
            tee(fh, "[sim] RUN TIMED OUT")
            sys.exit(2)

        out = rr.stdout + rr.stderr
        for ln in out.splitlines():
            tee(fh, " ", ln)

        verdict = "PASS" if "\nPASS" in "\n" + out or out.strip().startswith("PASS") \
            else ("PASS" if any(l.startswith("PASS") for l in out.splitlines()) else "FAIL")
        passed = any(l.startswith("PASS") for l in out.splitlines())
        tee(fh, f"[sim] verdict: {'PASS' if passed else 'FAIL'}  (log: {log_path})")
        sys.exit(0 if passed else 3)


if __name__ == "__main__":
    main()
