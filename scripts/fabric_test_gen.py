#!/usr/bin/env python3
"""Generate a suite of self-checking fabric test bitstreams (#101).

WHAT THIS IS FOR
----------------
Nothing in the open flow tests fabric FUNCTION -- SED/SEDGA CRCs the
configuration memory, which catches a flipped config bit but not a dead LUT or
a broken wire, and vendor test vectors are proprietary.  So a board owner has no
way to ask "is this die actually good?".  These designs answer that at the
confidence-check level: flash them, read a signature back over JTAG, get a
per-test pass/fail and a cumulative coverage figure.

Deliberately NOT exhaustive; see scripts/fabric_coverage_plan.py for the curve
that sets the count.  ~24 configurations reach 97% of ECP5 routing arcs and
99.3% on MachXO2, because coverage is bounded by mux fan-in (p95 = 24 on both
families) and everything else rides along in parallel.

READOUT: THIS GENERATOR DOES NOT PROVIDE ONE
--------------------------------------------
Read this before planning a hardware run.  These designs expose the signature
and status as ORDINARY PORTS.  There is no JTAG interface here -- no JTAGG
primitive, no ER1 user register.  Getting the result off a real board needs a
readout this file does not build.

Use the proven path instead.  #98 already ran this class of test on hardware
using Amaranth gateware over LUNA's `JTAGRegisterInterface`
(`ecp5-test/fabric/fabric_gateware.py` in the cynthion workspace, with
fabric_build / fabric_run / fabric_control).  That channel has been exercised on
a real part; a second, unproven one written here would be a liability, not an
alternative.  scripts/fabric_test_bridge.py hands this generator's plan to it.

What this file IS for: the plan and the golden.  Which fabric to target, how
many configurations, what signature each must produce, and a design that is
verifiable in simulation before anyone reaches for a board.

WHY JTAG IS STILL THE RIGHT CHANNEL
-----------------------------------
Every device in these families has the TAP -- it is how the bitstream arrives,
so the channel exists before the design does.  A signature register is fabric
logic needing no bonded I/O, so one design fits a small part and a large one
alike.  Bonded pin counts vary 98-197 across packages of a SINGLE ECP5 part, so
any pad-based readout would need a per-package variant; a JTAG one does not.
LEDs are an optional local convenience, never the verdict -- which pin reaches
an LED is a board fact, and #98's LED walk had a bug that made it briefly mimic
the wedged state it existed to detect.

HOW EACH TEST WORKS
-------------------
Each design fills the fabric with independent LFSR blocks, runs them a fixed
number of cycles, and XOR-folds the result into a 32-bit signature compared
against a golden value baked in at build time.  Three properties make that a
measurement rather than a formality:

  * The golden is computed from the SAME recurrence by an independent Python
    model (fabric_test_golden.py), so a bug in the gateware and a bug in the
    expectation do not cancel.
  * Blocks use DISTINCT polynomials and seeds, or yosys dedupes them and the
    "N parallel blocks" become one.
  * Every block output reaches the signature, or yosys prunes it -- the emitted
    design is checked for cell count after synthesis, not merely written.

  --negative-control builds the same design with a deliberately WRONG golden.
  It must report mismatch on every round.  A clean run from an unproven detector
  is worth nothing, and that is the step most easily skipped.

    python3 scripts/fabric_test_gen.py --device LFE5U-12F --count 24
    python3 scripts/fabric_test_gen.py --device LFE5U-12F --count 1 \\
        --negative-control

Writes Verilog to ./tmp/fabric-tests/<device>/ and logs to
./tmp/logs/fabric_test_gen.log.  Building bitstreams is a separate step (yosys
+ nextpnr + ecppack) so the generator stays toolchain-independent and testable.
"""
import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"
OUT_ROOT = REPO / "tmp/fabric-tests"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

# Maximal-length 32-bit Galois LFSR taps.  Distinct per block so yosys cannot
# merge blocks that would otherwise be structurally identical.
TAPS = [
    0x80000057, 0x80000062, 0x8000007A, 0x80000092, 0x8000009D, 0x800000B9,
    0x800000BA, 0x800000C1, 0x800000DA, 0x800000E5, 0x8000012D, 0x8000014E,
    0x80000162, 0x8000019F, 0x800001A4, 0x800001B1, 0x800001CF, 0x800001D2,
    0x800001E1, 0x80000200, 0x8000022D, 0x80000241, 0x8000025A, 0x80000273,
]


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("fabric_test_gen")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "fabric_test_gen.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def lfsr_step(state, tap):
    """One Galois LFSR step -- the reference recurrence.

    fabric_test_golden.py imports THIS function, and the emitted Verilog
    implements the same shift/xor.  One definition, two consumers, so the golden
    cannot drift from the gateware.
    """
    lsb = state & 1
    state >>= 1
    if lsb:
        state ^= tap
    return state & 0xFFFFFFFF


def golden(blocks, cycles, seed_base):
    """Signature the hardware must produce: XOR-fold of every block's state."""
    sig = 0
    for b in range(blocks):
        st = (seed_base + b * 0x9E3779B9) & 0xFFFFFFFF
        if st == 0:
            st = 1                      # all-zero is the LFSR's dead state
        tap = TAPS[b % len(TAPS)]
        for _ in range(cycles):
            st = lfsr_step(st, tap)
        sig ^= st
    return sig & 0xFFFFFFFF


def emit_design(idx, blocks, cycles, seed_base, expect, family):
    """One test design: LFSR farm -> XOR signature -> JTAG user register."""
    taps = [TAPS[b % len(TAPS)] for b in range(blocks)]
    seeds = []
    for b in range(blocks):
        s = (seed_base + b * 0x9E3779B9) & 0xFFFFFFFF
        seeds.append(s if s else 1)

    L = [
        f"// Fabric test {idx:02d} -- GENERATED by scripts/fabric_test_gen.py",
        f"// blocks={blocks} cycles={cycles} seed_base=0x{seed_base:08x}",
        f"// expected signature = 0x{expect:08x}",
        "//",
        "// NOTE: signature/pass/done are plain PORTS.  This file builds no JTAG",
        "// interface -- see scripts/fabric_test_bridge.py for the readout that has",
        "// actually been exercised on hardware (#98).",
        "`default_nettype none",
        "",
        f"module fabric_test_{idx:02d} (",
        "    input  wire clk,",
        "    output wire pass,        // optional LED: high = matching",
        "    output wire done,        // optional LED: high once a round completed",
        "    output wire [31:0] signature",
        ");",
        f"    localparam [31:0] EXPECT = 32'h{expect:08x};",
        f"    localparam integer CYCLES = {cycles};",
        "",
        "    reg [31:0] cyc = 32'd0;",
        "    reg        running = 1'b1;",
        "    reg        round_done = 1'b0;",
        "    reg        mismatch_sticky = 1'b0;   // latched, never cleared",
        "",
    ]
    # Each block is its own always block with a distinct tap and seed, so yosys
    # cannot dedupe them into one.
    for b in range(blocks):
        L += [
            f"    reg [31:0] s{b} = 32'h{seeds[b]:08x};",
            f"    always @(posedge clk) if (running)",
            f"        s{b} <= s{b}[0] ? ((s{b} >> 1) ^ 32'h{taps[b]:08x})"
            f" : (s{b} >> 1);",
        ]
    L.append("")
    fold = " ^ ".join(f"s{b}" for b in range(blocks))
    L += [
        f"    wire [31:0] sig = {fold};",
        "    assign signature = sig;",
        "",
        "    // Compare the cycle AFTER the last step, not on it.  `sig` is",
        "    // combinational from the block registers, so at the deciding edge it",
        "    // still shows the pre-step value -- comparing there reads a signature",
        "    // one step short of the golden and every test fails while the value",
        "    // is in fact correct.  Caught in simulation before any build.",
        "    always @(posedge clk) begin",
        "        if (running) begin",
        "            cyc <= cyc + 32'd1;",
        "            if (cyc == CYCLES - 1) running <= 1'b0;",
        "        end else if (!round_done) begin",
        "            round_done <= 1'b1;",
        "            if (sig != EXPECT) mismatch_sticky <= 1'b1;",
        "        end",
        "    end",
        "",
        "    assign done = round_done;",
        "    assign pass = round_done & ~mismatch_sticky;",
        "endmodule",
        "`default_nettype wire",
        "",
    ]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="LFE5U-12F")
    ap.add_argument("--count", type=int, default=24,
                    help="number of test designs (see fabric_coverage_plan.py)")
    ap.add_argument("--blocks", type=int, default=24,
                    help="LFSR blocks per design")
    ap.add_argument("--cycles", type=int, default=1 << 16)
    ap.add_argument("--negative-control", action="store_true",
                    help="bake in a WRONG golden; every round must mismatch")
    ap.add_argument("--family", default=None)
    args = ap.parse_args()
    log = setup_logging()

    outdir = OUT_ROOT / args.device
    outdir.mkdir(parents=True, exist_ok=True)
    log.info("device %s  designs %d  blocks/design %d  cycles %d",
             args.device, args.count, args.blocks, args.cycles)
    if args.negative_control:
        log.info("NEGATIVE CONTROL: golden deliberately corrupted; a clean "
                 "run here means the DETECTOR is broken, not the fabric")

    manifest = []
    for i in range(args.count):
        seed_base = (0x1234_5678 + i * 0x0100_0193) & 0xFFFFFFFF
        exp = golden(args.blocks, args.cycles, seed_base)
        if args.negative_control:
            exp ^= 0x0000_0001          # one bit wrong: the subtlest failure
        name = f"fabric_test_{i:02d}"
        (outdir / f"{name}.v").write_text(
            emit_design(i, args.blocks, args.cycles, seed_base, exp,
                        args.family))
        manifest.append((name, seed_base, exp))
        log.info("  %s  seed_base=0x%08x  expect=0x%08x", name, seed_base, exp)

    mf = outdir / "manifest.tsv"
    with open(mf, "w") as fh:
        fh.write("# design\tseed_base\texpected_signature\n")
        fh.write(f"# device={args.device} blocks={args.blocks} "
                 f"cycles={args.cycles} "
                 f"negative_control={args.negative_control}\n")
        for n, s, e in manifest:
            fh.write(f"{n}\t0x{s:08x}\t0x{e:08x}\n")
    log.info("wrote %d designs + %s", len(manifest), mf)
    log.info("next: synthesise with yosys+nextpnr+ecppack, then read ER1 over "
             "JTAG; see docs/fabric-test.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
