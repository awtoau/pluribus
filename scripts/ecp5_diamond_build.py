#!/usr/bin/env python3
"""Build ECP5 bitstreams with Lattice Diamond, as a second-toolchain oracle.

WHY DIAMOND RATHER THAN MORE nextpnr BUILDS
-------------------------------------------
The ECP5 lifter was verified against 18 designs that yosys+nextpnr+prjtrellis
built, using nextpnr's own placed netlist as the oracle.  That loop is closed:
the same project produced the bitstream, the reference netlist AND the tile
database.  It cannot detect a shared assumption.

Diamond is a completely independent implementation — different synthesis
(LSE/Synplify), different packer, different router, different bitgen — and it
targets the same silicon.  A Diamond-built bitstream of a design we wrote is
therefore the single most informative test available: we know what the design
IS, so a decode can be judged, and nothing about the file came from the
toolchain under test.

Diamond also packs differently on purpose.  It is far more willing to use the
wide-mux path (F5MUX/PFUMX/L6MUX21) and the CCU2 carry chain than nextpnr is
for small designs, which is exactly where the lifter's known gaps live.  The
designs below are chosen to force those structures rather than avoid them.

DESIGNS
-------
  dm_counter    CCU2 carry chain — a wide binary counter, nothing else.
  dm_wide_mux   forces F5MUX/PFUMX/L6MUX21 via a big combinational mux.
  dm_multiclk   several independent clock domains — clock-global recovery.
  dm_shiftreg   long shift register — dense FF packing, few LUTs.
  dm_mixed      all of the above in one design, plus block RAM.

Usage:
    python3 scripts/ecp5_diamond_build.py [--only NAME] [--device DEV] [--jobs N]

Logs to ./tmp/logs/ecp5_diamond_build.log.  Bitstreams land in
corpus/diamond/<name>/ (gitignored; they are OUR builds but still binaries).
"""
import argparse
import concurrent.futures
import logging
import os
import shutil
import subprocess
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_ROOT = os.path.join(REPO, "corpus", "diamond")

DIAMOND = os.environ.get("DIAMONDDIR",
                         os.path.expanduser("~/lscc/diamond/3.14"))
DIAMONDC = os.path.join(DIAMOND, "bin", "lin64", "diamondc")
LICENSE = os.environ.get(
    "LM_LICENSE_FILE", os.path.join(DIAMOND, "license", "license.dat"))

# LFE5U-25F in caBGA381 -- a real part, in the Trellis DB, and NOT the 12F
# every existing test used.  Choosing a different die than the verified one is
# deliberate: geometry_for() has only ever been exercised on 12F.
DEFAULT_DEVICE = "LFE5U-25F-6MG285I"
DEFAULT_TRELLIS_DEV = "LFE5U-25F"

_lock = threading.Lock()


def setup_logging(name):
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(REPO, "tmp", "logs",
                                               f"{name}.log"))):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


# ---------------------------------------------------------------------------
# designs
# ---------------------------------------------------------------------------

DESIGNS = {
    # A 24-bit counter is a pure carry chain.  Diamond maps this to CCU2C
    # cells, so the FCI/FCO path the lifter does not model is the ONLY thing
    # holding the arithmetic together -- the ideal probe for that gap.
    "dm_counter": """
module top(input clk, input rst, output [7:0] led);
  reg [23:0] cnt;
  always @(posedge clk) begin
    if (rst) cnt <= 24'd0;
    else     cnt <= cnt + 24'd1;
  end
  assign led = cnt[23:16];
endmodule
""",

    # A 16:1 mux over 8-bit data.  Too wide for a single LUT4, so the packer
    # must use the slice's dedicated wide-mux path (F5MUX/PFUMX/L6MUX21).
    "dm_wide_mux": """
module top(input clk, input [3:0] sel, input [15:0] d, output reg q);
  wire m = d[sel];
  always @(posedge clk) q <= m;
endmodule
""",

    # Three unrelated clocks.  prjtrellis parks non-TAP/SPINE globals at (0,0),
    # so the lifter drops them; this measures how much of a real multi-domain
    # design that costs.
    "dm_multiclk": """
module top(input clka, input clkb, input clkc,
           input da, input db, input dc,
           output reg qa, output reg qb, output reg qc);
  reg [7:0] sa, sb, sc;
  always @(posedge clka) begin sa <= {sa[6:0], da}; qa <= ^sa; end
  always @(posedge clkb) begin sb <= {sb[6:0], db}; qb <= ^sb; end
  always @(posedge clkc) begin sc <= {sc[6:0], dc}; qc <= ^sc; end
endmodule
""",

    # 128 FFs in a chain, almost no combinational logic.  Dense FF packing
    # exercises REG0/REG1 pairing and the CE/LSR control muxes.
    "dm_shiftreg": """
module top(input clk, input ce, input d, output q);
  reg [127:0] sr;
  always @(posedge clk) if (ce) sr <= {sr[126:0], d};
  assign q = sr[127];
endmodule
""",

    # Everything at once, plus inferred block RAM -- the shape of a real
    # design rather than a microbenchmark.
    "dm_mixed": """
module top(input clk, input rst, input [3:0] sel, input [15:0] din,
           input we, input [7:0] addr, output reg [15:0] dout);
  reg [15:0] mem [0:255];
  reg [19:0] cnt;
  wire [15:0] sh = din << sel;
  always @(posedge clk) begin
    if (rst) cnt <= 20'd0; else cnt <= cnt + 20'd1;
    if (we) mem[addr] <= sh ^ cnt[15:0];
    dout <= mem[addr];
  end
endmodule
""",
}


def lpf_for(name, device):
    """Minimal LPF.  We deliberately do NOT pin-assign: letting Diamond place
    the IO where it likes is closer to how a third-party design arrives, and
    a bad hand-picked pin just makes the build fail for an irrelevant reason."""
    return "BLOCK RESETPATHS;\nBLOCK ASYNCPATHS;\n"


LDF = """<?xml version="1.0" encoding="UTF-8"?>
<BaliProject version="3.2" title="{name}" device="{device}" default_implementation="impl1">
    <Options/>
    <Implementation title="impl1" dir="impl1" description="impl1" synthesis="lse" default_strategy="Strategy1">
        <Options/>
        <Source name="{name}.v" type="Verilog" type_short="Verilog"><Options/></Source>
        <Source name="{name}.lpf" type="Logic Preference" type_short="LPF"><Options/></Source>
    </Implementation>
    <Strategy name="Strategy1" file="{sty}"/>
</BaliProject>
"""

RUN_TCL = """prj_project open "{ldf}"
prj_run PAR -impl impl1
prj_run Export -impl impl1 -task Bitgen
prj_project close
"""


def build_one(name, src, device, log):
    # Key the build directory by DIE as well as design.  Building the same
    # design for 25F and 45F is the point (different frame geometry), so they
    # must not overwrite each other.
    die = device.split("-")[0] + "-" + device.split("-")[1]
    d = os.path.join(BUILD_ROOT, f"{die}_{name}")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{name}.v"), "w") as fh:
        fh.write(src)
    with open(os.path.join(d, f"{name}.lpf"), "w") as fh:
        fh.write(lpf_for(name, device))
    sty = os.path.join(REPO, "diamond-fuzz", "aw21.sty")
    with open(os.path.join(d, f"{name}.ldf"), "w") as fh:
        fh.write(LDF.format(name=name, device=device, sty=sty))
    ldf = os.path.join(d, f"{name}.ldf")
    tcl = os.path.join(d, "run.tcl")
    with open(tcl, "w") as fh:
        fh.write(RUN_TCL.format(ldf=ldf))

    env = dict(os.environ)
    env["LM_LICENSE_FILE"] = LICENSE
    env["bindir"] = os.path.join(DIAMOND, "bin", "lin64")
    env["LD_LIBRARY_PATH"] = os.pathsep.join(
        [os.path.join(DIAMOND, "bin", "lin64"),
         os.path.join(DIAMOND, "ispfpga", "bin", "lin64"),
         env.get("LD_LIBRARY_PATH", "")])

    r = subprocess.run([DIAMONDC, tcl], cwd=d, capture_output=True, text=True,
                       env=env)
    logtxt = (r.stdout or "") + (r.stderr or "")
    with open(os.path.join(d, "diamond.log"), "w") as fh:
        fh.write(logtxt)

    bit = None
    for root, _dirs, files in os.walk(d):
        for f in files:
            if f.endswith(".bit"):
                bit = os.path.join(root, f)
    with _lock:
        if bit and os.path.getsize(bit) > 0:
            log.info("%-14s BUILT  %s (%d B)", name,
                     os.path.relpath(bit, REPO), os.path.getsize(bit))
        else:
            log.error("%-14s FAILED rc=%d", name, r.returncode)
            for ln in logtxt.strip().splitlines()[-15:]:
                log.error("      %s", ln)
    return name, bit, r.returncode, logtxt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--device", default=DEFAULT_DEVICE)
    ap.add_argument("--jobs", type=int, default=3)
    args = ap.parse_args()
    log = setup_logging("ecp5_diamond_build")

    if not os.path.exists(DIAMONDC):
        log.error("diamondc not found at %s -- set DIAMONDDIR", DIAMONDC)
        return 2
    log.info("diamond=%s device=%s license=%s", DIAMOND, args.device, LICENSE)

    todo = {k: v for k, v in DESIGNS.items()
            if not args.only or k in args.only}
    os.makedirs(BUILD_ROOT, exist_ok=True)

    results = []
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as ex:
        futs = [ex.submit(build_one, n, s, args.device, log)
                for n, s in todo.items()]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())

    ok = [r for r in results if r[1]]
    log.info("---- %d/%d built ----", len(ok), len(results))
    for name, bit, _rc, _l in sorted(results):
        log.info("  %-14s %s", name, os.path.relpath(bit, REPO) if bit else "FAILED")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
