#!/usr/bin/env python3
"""Verify a generated fabric-test suite in simulation, before any hardware (#101).

Two jobs, and the second is the one that matters:

  1. Every test must PASS in simulation.  A design that cannot pass against a
     perfect simulated fabric will never pass on silicon, and debugging that on
     a board wastes the trip.
  2. The NEGATIVE CONTROL must FAIL.  The same design with one bit wrong in the
     golden has to report mismatch.  Without this, a clean hardware run proves
     only that the detector is silent -- which is also what a broken detector
     looks like.  #98's result rests on exactly this step and it is the one most
     easily skipped.

It also reports the synthesised cell counts, because "N parallel blocks" is a
claim yosys can quietly falsify: identical blocks get deduped into one, and a
block whose output reaches nothing gets pruned. Distinct taps and seeds prevent
the first, folding every block into the signature prevents the second, and this
prints the numbers so neither is taken on trust.

    python3 scripts/fabric_test_verify.py --dir tmp/fabric-tests/LFE5U-12F

Logs to ./tmp/logs/fabric_test_verify.log.
"""
import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = REPO / "tmp"
LOG_DIR = TMP / "logs"

TB = """`timescale 1ns/1ps
module ft_tb;
    reg clk = 0; always #5 clk = ~clk;
    wire pass, done; wire [31:0] sig;
    {top} dut(.clk(clk), .pass(pass), .done(done), .signature(sig));
    initial begin
        wait(done);
        #1 $display("SIG %08x PASS %0d", sig, pass);
        $finish;
    end
endmodule
"""


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("fabric_test_verify")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "fabric_test_verify.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def simulate(vfile, top, work):
    tb = work / f"tb_{top}.v"
    tb.write_text(TB.format(top=top))
    vvp = work / f"{top}.vvp"
    r = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), "-s", "ft_tb",
                        str(tb), str(vfile)], capture_output=True, text=True)
    if r.returncode != 0:
        return None, None, (r.stderr or r.stdout).strip()[:300]
    r = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True)
    m = re.search(r"SIG ([0-9a-f]{8}) PASS (\d)", r.stdout)
    if not m:
        return None, None, r.stdout.strip()[:300]
    return m.group(1), m.group(2) == "1", None


def synth_stats(vfile, top):
    """Cell counts after synth_ecp5 -- proof the blocks were not optimised away."""
    r = subprocess.run(
        ["yosys", "-p", f"read_verilog {vfile}; synth_ecp5 -top {top}"],
        capture_output=True, text=True)
    out = r.stdout
    cells = {}
    for name in ("TRELLIS_FF", "LUT4", "CCU2C", "PFUMX", "L6MUX21"):
        m = re.search(rf"^\s+(\d+)\s+{name}\s*$", out, re.M)
        if m:
            cells[name] = int(m.group(1))
    return cells


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="generated suite directory")
    ap.add_argument("--expect-fail", action="store_true",
                    help="this is a negative-control suite: every test MUST fail")
    ap.add_argument("--no-synth", action="store_true")
    args = ap.parse_args()
    log = setup_logging()

    d = Path(args.dir)
    designs = sorted(d.glob("fabric_test_*.v"))
    if not designs:
        raise SystemExit(f"no fabric_test_*.v under {d}")
    work = TMP / "fabric-test-work"
    work.mkdir(parents=True, exist_ok=True)
    log.info("%d design(s) in %s%s", len(designs), d,
             "   [NEGATIVE CONTROL: all must FAIL]" if args.expect_fail else "")

    ok = bad = 0
    for v in designs:
        top = v.stem
        sig, passed, err = simulate(v, top, work)
        if err:
            log.error("%s  SIM ERROR: %s", top, err)
            bad += 1
            continue
        want = not args.expect_fail
        good = (passed == want)
        log.info("%s  sig=%s  pass=%s  %s", top, sig, passed,
                 "OK" if good else "*** UNEXPECTED ***")
        ok, bad = (ok + 1, bad) if good else (ok, bad + 1)

    if not args.no_synth and designs:
        st = synth_stats(designs[0], designs[0].stem)
        log.info("")
        log.info("synthesis of %s: %s", designs[0].stem,
                 "  ".join(f"{k}={v}" for k, v in st.items()) or "(no stats)")
        ff = st.get("TRELLIS_FF", 0)
        log.info("flip-flops %d -- if this is near 32 rather than 32*blocks, "
                 "yosys deduped the blocks and the parallelism is illusory", ff)

    log.info("")
    verdict = "PASS" if bad == 0 else "FAIL"
    log.info("==== %s: %d as expected, %d unexpected ====", verdict, ok, bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
