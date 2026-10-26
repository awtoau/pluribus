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
  dm_mux32/64   32:1 / 64:1 mux: L6MUX21 and a second wide-mux level.
  dm_add_cmp    CCU2 adder + comparator (carry chain with two operands).
  dm_ebr_dp     simple dual-port RAM on two clocks (EBR, two clock pins).
  dm_distram    small RAM (distributed RAM: DPRAM/RAMW slices).
  dm_dsp        registered 18x18 multiplier (DSP).
  dm_gsr        GSR primitive: slices with GSR=ENABLED (the bits.db default, #118).

Usage:
    python3.15t scripts/ecp5_diamond_build.py [--only NAME] [--die 25F|45F|85F] [--jobs N] [--force]

Existing builds (routed .ncd + .bit) are reused unless --force.

Logs to ./tmp/logs/ecp5_diamond_build.log.  Builds land in
<data-root>/corpus/diamond/<die>_<name>/ (gitignored; OUR builds but still
binaries).  data-root = this checkout, else the main checkout (shared cache).
"""
import argparse
import concurrent.futures
import glob
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heavy_guard  # noqa: E402
from ecp5_diamond_oracle import data_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_ROOT = os.path.join(data_root(), "corpus", "diamond")

# Parts of the existing corpus (docs/ecp5-diamond-oracle.md), one per die.
DEVICES = {"25F": "LFE5U-25F-6MG285I", "45F": "LFE5U-45F-6BG554C",
           "85F": "LFE5U-85F-7BG554C"}

DIAMOND = os.environ.get("DIAMONDDIR",
                         os.path.expanduser("~/lscc/diamond/3.14"))
DIAMONDC = os.path.join(DIAMOND, "bin", "lin64", "diamondc")
LICENSE = os.environ.get(
    "LM_LICENSE_FILE", os.path.join(DIAMOND, "license", "license.dat"))

# LFE5U-25F in caBGA381 -- a real part, in the Trellis DB, and NOT the 12F
# every existing test used.  Choosing a different die than the verified one is
# deliberate: geometry_for() has only ever been exercised on 12F.
DEFAULT_DEVICE = DEVICES["25F"]

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

    # 32:1 and 64:1 muxes: beyond one L5/PFUMX level, forces L6MUX21.
    "dm_mux32": """
module top(input clk, input [4:0] sel, input [31:0] d, output reg q);
  wire m = d[sel];
  always @(posedge clk) q <= m;
endmodule
""",
    "dm_mux64": """
module top(input clk, input [5:0] sel, input [63:0] d, output reg q);
  wire m = d[sel];
  always @(posedge clk) q <= m;
endmodule
""",

    # Adder + comparator on registered operands: CCU2 chains with two inputs.
    "dm_add_cmp": """
module top(input clk, input [15:0] a, input [15:0] b,
           output reg [16:0] s, output reg lt);
  reg [15:0] ra, rb;
  always @(posedge clk) begin
    ra <= a; rb <= b;
    s <= ra + rb;
    lt <= ra < rb;
  end
endmodule
""",

    # Simple dual-port RAM, independent read/write clocks: EBR with two clocks.
    "dm_ebr_dp": """
module top(input wclk, input rclk, input we, input [8:0] waddr,
           input [8:0] raddr, input [17:0] din, output reg [17:0] dout);
  reg [17:0] mem [0:511];
  always @(posedge wclk) if (we) mem[waddr] <= din;
  always @(posedge rclk) dout <= mem[raddr];
endmodule
""",

    # 16x8 RAM with async read: distributed RAM (DPRAM/RAMW slices).
    "dm_distram": """
module top(input clk, input we, input [3:0] waddr, input [3:0] raddr,
           input [7:0] din, output [7:0] dout);
  reg [7:0] mem [0:15];
  always @(posedge clk) if (we) mem[waddr] <= din;
  assign dout = mem[raddr];
endmodule
""",

    # GSR primitive: registers get GSR:ENABLED, which the bitstream omits (DB default).
    "dm_gsr": """
module top(input clk, input rst_n, input d, output q);
  reg [7:0] sr;
  GSR GSR_INST (.GSR(rst_n));
  always @(posedge clk) sr <= {sr[6:0], d};
  assign q = sr[7];
endmodule
""",

    # Registered 18x18 multiply: DSP block.
    "dm_dsp": """
module top(input clk, input [17:0] a, input [17:0] b, output reg [35:0] p);
  reg [17:0] ra, rb;
  always @(posedge clk) begin
    ra <= a; rb <= b;
    p <= ra * rb;
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


def build_dir(name, device):
    # Key by DIE as well as design: same design on 25F/45F/85F must not overwrite.
    die = device.split("-")[0] + "-" + device.split("-")[1]
    return os.path.join(BUILD_ROOT, f"{die}_{name}")


def built_files(d):
    """-> (ncd, bit) of a finished routed build under d, else (None, None)."""
    imp = os.path.join(d, "impl1")
    ncd = [f for f in glob.glob(os.path.join(imp, "*_impl1.ncd"))]
    bit = [f for f in glob.glob(os.path.join(imp, "*_impl1.bit")) if os.path.getsize(f) > 0]
    return (ncd[0], bit[0]) if ncd and bit else (None, None)


def build_one(name, src, device, log, force=False):
    d = build_dir(name, device)
    if not force and all(built_files(d)):
        log.info("%-14s %s REUSED", name, device)
        return name, built_files(d)[1], 0, ""
    heavy_guard.wait_available(log, name)
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

    r = heavy_guard.guarded([DIAMONDC, tcl], f"diamondc {name} {device}", log, cwd=d, env=env)  # #122
    logtxt = (r.stdout or "") + (r.stderr or "")
    with open(os.path.join(d, "diamond.log"), "w") as fh:
        fh.write(logtxt)

    ncd, bit = built_files(d)
    with _lock:
        if bit:
            log.info("%-14s %s BUILT  %s (%d B)", name, device,
                     os.path.relpath(bit, BUILD_ROOT), os.path.getsize(bit))
        else:
            log.error("%-14s %s FAILED rc=%d", name, device, r.returncode)
            for ln in logtxt.strip().splitlines()[-15:]:
                log.error("      %s", ln)
    return name, bit, r.returncode, logtxt


def ensure_built(names, dies, log, jobs=3, force=False):
    """Build every (design, die) lacking a routed NCD + bit.  Caller holds the
    heavy lock.  Returns the list of "<die>_<name>" that failed."""
    os.makedirs(BUILD_ROOT, exist_ok=True)
    jobs_l = [(n, DEVICES[d]) for d in dies for n in names]
    failed = []
    with concurrent.futures.ThreadPoolExecutor(jobs) as ex:
        futs = {ex.submit(build_one, n, DESIGNS[n], dev, log, force): (n, dev)
                for n, dev in jobs_l}
        for f in concurrent.futures.as_completed(futs):
            n, dev = futs[f]
            if not f.result()[1]:
                failed.append(os.path.basename(build_dir(n, dev)))
    return sorted(failed)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--die", action="append", choices=sorted(DEVICES),
                    help="default: 25F only (as before); repeat for several")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    log = setup_logging("ecp5_diamond_build")

    if not os.path.exists(DIAMONDC):
        log.error("diamondc not found at %s -- set DIAMONDDIR", DIAMOND)
        return 2
    dies = args.die or ["25F"]
    names = [k for k in DESIGNS if not args.only or k in args.only]
    log.info("diamond=%s dies=%s license=%s", DIAMOND, dies, LICENSE)
    with heavy_guard.heavy_lock("ecp5_diamond_build", log):
        failed = ensure_built(names, dies, log, args.jobs, args.force)
    log.info("---- %d/%d built ----", len(names) * len(dies) - len(failed),
             len(names) * len(dies))
    for f in failed:
        log.info("  FAILED %s", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
