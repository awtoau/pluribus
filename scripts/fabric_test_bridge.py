#!/usr/bin/env python3
"""Hand a fabric coverage plan to gateware that already has a working readout (#101).

WHY A BRIDGE RATHER THAN MORE GATEWARE
--------------------------------------
scripts/fabric_test_gen.py emits designs whose signature and status are ordinary
PORTS.  Getting a result off a real board needs a JTAG readout it does not
build.  Rather than write a second one, this points the plan at the one that has
already been exercised on silicon: #98's Amaranth gateware over LUNA's
`JTAGRegisterInterface`, which ran 2,002 clean rounds on a Cynthion r1.4 and
whose negative control reported 1,575/1,575 mismatches.

A second, unproven readout would be a liability.  The failure mode is specific
and was seen in #98: the LED liveness walk had a bug that made it briefly mimic
the wedged state it existed to detect.  Harmless there, because JTAG carried the
verdict.  The same bug in the primary channel is a false negative -- a fabric
test that cannot report failure is indistinguishable from one that found none.

WHAT THIS DOES
--------------
Reads a generated manifest (design, seed, expected signature) and emits the
fabric_build.py invocations that realise it, one per configuration.  It prints
commands rather than running them: the build tooling lives in another repo with
its own toolchain, and a script that silently shells into a sibling checkout is
harder to audit than one that shows you the command.

    python3 scripts/fabric_test_bridge.py \\
        --manifest tmp/fabric-tests/LFE5U-12F/manifest.tsv

    # then, in the workspace that owns the gateware:
    python3 scripts/fabric_build.py --blocks N --golden 0x... --round-bits 18

DIVISION OF LABOUR
------------------
  pluribus            WHAT to test -- which fabric, how many configurations,
                      what signature each must produce, verified in simulation.
  the board workspace HOW to run it -- build, load, read JTAG, negative control.

That split is deliberate.  The plan is device data and belongs with the engine
that measured the fabric; the readout is board- and toolchain-specific and
belongs with the board.

Logs to ./tmp/logs/fabric_test_bridge.log.
"""
import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("fabric_test_bridge")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "fabric_test_bridge.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def read_manifest(path):
    """(designs, meta) from a fabric_test_gen manifest."""
    designs, meta = [], {}
    for ln in Path(path).read_text().splitlines():
        if ln.startswith("#"):
            for tok in ln.lstrip("# ").split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    meta[k] = v
            continue
        if not ln.strip():
            continue
        f = ln.split("\t")
        if len(f) >= 3:
            designs.append((f[0], f[1], f[2]))
    return designs, meta


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--build-script", default="scripts/fabric_build.py",
                    help="path to fabric_build.py IN THE BOARD WORKSPACE")
    ap.add_argument("--emit-golden", action="store_true",
                    help="also pass --golden from this plan.  ONLY correct when "
                         "the target gateware uses the SAME recurrence as "
                         "fabric_test_gen.lfsr_step; #98's does not.")
    ap.add_argument("--min-luts", type=int, default=None,
                    help="refuse to build below this utilisation; #98 used a "
                         "floor so the test could not silently shrink")
    args = ap.parse_args()
    log = setup_logging()

    designs, meta = read_manifest(args.manifest)
    if not designs:
        raise SystemExit(f"no designs in {args.manifest}")

    blocks = meta.get("blocks", "?")
    cycles = int(meta.get("cycles", "0") or 0)
    negctl = meta.get("negative_control", "False") == "True"
    round_bits = cycles.bit_length() - 1 if cycles and not (cycles & (cycles - 1)) else None

    log.info("manifest %s", args.manifest)
    log.info("  device=%s blocks=%s cycles=%s%s", meta.get("device", "?"),
             blocks, cycles, "  [NEGATIVE CONTROL]" if negctl else "")
    if round_bits is None and cycles:
        log.warning("  cycles=%s is not a power of two; fabric_build.py takes "
                    "--round-bits, so pick a power-of-two cycle count",
                    cycles)
    log.info("")
    if negctl:
        log.info("These builds carry a WRONG golden ON PURPOSE.  Every round "
                 "must report a mismatch; a clean run means the DETECTOR is "
                 "broken, not the fabric.")
        log.info("")

    log.warning("GOLDEN VALUES ARE NOT PORTABLE BETWEEN RECURRENCES.")
    log.warning("  This generator uses a plain Galois LFSR.  #98's gateware adds a")
    log.warning("  nonlinear mix -- rotl(3)&rotl(17), rotl(11)|rotl(29) -- so it")
    log.warning("  produces DIFFERENT signatures from the same seeds.  Passing a")
    log.warning("  golden computed here to that gateware makes every round mismatch,")
    log.warning("  which looks exactly like a dead fabric.")
    log.warning("  Let fabric_build.py compute its own golden (omit --golden), and")
    log.warning("  take from this plan only the COUNT, the blocks and the round size.")
    log.info("")
    log.info("Run these in the workspace that owns the gateware:")
    log.info("")
    for name, seed, exp in designs:
        cmd = [f"python3 {args.build_script}", f"--blocks {blocks}"]
        if args.emit_golden:
            cmd.append(f"--golden {exp}")
        if round_bits is not None:
            cmd.append(f"--round-bits {round_bits}")
        if args.min_luts:
            cmd.append(f"--min-luts {args.min_luts}")
        log.info("  # %s  (seed %s)", name, seed)
        log.info("  %s", " ".join(cmd))
    log.info("")
    log.info("Then load VOLATILE (SRAM, not flash) and read the JTAG registers; "
             "see docs/fabric-test.md.")
    log.info("Report cumulatively: 'k/%d passed' is only meaningful with the "
             "coverage share attached -- see scripts/fabric_coverage_plan.py.",
             len(designs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
