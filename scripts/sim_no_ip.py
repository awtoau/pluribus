#!/usr/bin/env python3
"""Simulate a recovered netlist with the hard IP replaced by open logic.

A recovered netlist emits the EFB as a (* blackbox *): correct, since its
internals are not in the bitstream.  But a blackbox drives nothing, so every
fabric net it feeds sits at X and the recovered datapath never moves --
`sim_replacement.py` on a recovered design shows a quiet netlist and tells you
little.

This builds an IP-FREE variant: strip the blackbox stub, substitute the open
WISHBONE model (scripts/efb_open_model.v), apply the board's own register writes
(scripts/efb_boot_gen.py -> efb_wb_boot.vh), and run it.  Everything downstream
of the bus is the RECOVERED FABRIC, unmodified -- which is the point.

    python3 scripts/sim_no_ip.py --rtl out/V07.v --tb out/V07_tb.v \\
        --board boards/aw2-2d82auto [--top aw2_tb]

Logs + verdict to ./tmp/logs/sim_no_ip.log; VCD beside the vvp in ./tmp/.

WHAT A RESULT HERE MEANS.  Register STORAGE is faithful; register SEMANTICS are
not modelled (writing ARM_CAPTURE stores 0x07, it does not command hard IP to
capture).  So activity observed downstream comes from the recovered fabric
reacting to the bus.  That is evidence the fabric was recovered as working
logic; it is NOT evidence the board behaves this way, and the two should not be
conflated when reporting.
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

_BLACKBOX_RE = re.compile(
    r"\(\*\s*blackbox\s*\*\)\s*\n\s*module\s+EFB\s*\(.*?\n\s*endmodule\s*\n",
    re.S)


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("sim_no_ip")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "sim_no_ip.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def strip_blackbox(rtl_text, log):
    """Remove the (* blackbox *) EFB stub so the open model can take its place."""
    stripped, n = _BLACKBOX_RE.subn(
        "// EFB blackbox stub removed by scripts/sim_no_ip.py; the open model in\n"
        "// scripts/efb_open_model.v provides this module instead.\n", rtl_text)
    if n != 1:
        log.warning("expected exactly 1 EFB blackbox stub, removed %d", n)
    return stripped


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rtl", required=True, help="recovered netlist (.v)")
    ap.add_argument("--tb", required=True, help="testbench (.v)")
    ap.add_argument("--board", help="board dir; regenerates the boot sequence")
    ap.add_argument("--top", default="aw2_tb")
    ap.add_argument("--model", default=str(REPO / "scripts/efb_open_model.v"))
    args = ap.parse_args()
    log = setup_logging()
    TMP.mkdir(exist_ok=True)

    if args.board:
        subprocess.run([sys.executable, str(REPO / "scripts/efb_boot_gen.py"),
                        "--board", args.board], check=False,
                       capture_output=True)

    rtl = Path(args.rtl).read_text()
    noip = TMP / (Path(args.rtl).stem + "_noip.v")
    noip.write_text(strip_blackbox(rtl, log))
    log.info("wrote %s (%d bytes)", noip, noip.stat().st_size)

    # The generated testbench knows nothing about the boot sequence -- verilog.py
    # writes it for the blackbox case, where there is nothing to configure.  Splice
    # the register writes in at the start of its initial block, after $dumpvars so
    # the pokes are visible in the VCD.  Without this the open model is present but
    # never written to, and the run is indistinguishable from the blackbox one --
    # which is exactly what the first attempt produced.
    tb_text = Path(args.tb).read_text()
    boot_inc = REPO / "scripts/efb_wb_boot.vh"
    tb_out = Path(args.tb)
    if boot_inc.is_file() and "EFB_BOOT_SEQUENCE" not in tb_text:
        anchor = "$monitor("
        i = tb_text.find(anchor)
        if i < 0:
            log.warning("no $monitor in testbench; boot sequence NOT applied")
        else:
            j = tb_text.find(";", i) + 1
            inject = ("\n        // --- EFB register writes (scripts/efb_boot_gen.py) ---\n"
                      "        `EFB_BOOT_SEQUENCE\n"
                      "        #100;   // let the fabric see the configured bus\n")
            tb_text = (f'`include "{boot_inc}"\n' + tb_text[:j] + inject
                       + tb_text[j:])
            tb_out = TMP / (Path(args.tb).stem + "_noip.v")
            tb_out.write_text(tb_text)
            log.info("spliced boot sequence into %s", tb_out)
    args.tb = str(tb_out)

    vvp = TMP / (Path(args.rtl).stem + "_noip.vvp")
    cmd = ["iverilog", "-g2012", "-o", str(vvp), "-s", args.top,
           str(noip), str(args.model), str(args.tb)]
    log.info("compile: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0:
        log.error("COMPILE FAILED\n%s", (r.stderr or r.stdout)[-3000:])
        return 1
    if r.stderr.strip():
        log.info("compile warnings:\n%s", r.stderr.strip()[:1500])

    r = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True,
                       cwd=str(TMP))
    out = r.stdout + r.stderr
    log.info("---- simulation output ----")
    for line in out.splitlines():
        log.info("  %s", line)

    # A recovered netlist has no self-check to pass, so "did anything happen?"
    # is the honest measure: count monitor lines showing a state change.
    transitions = sum(1 for l in out.splitlines() if l.strip().startswith("t="))
    log.info("---- %d monitor transitions ----", transitions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
