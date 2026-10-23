#!/usr/bin/env python3
"""Self-test lifters/cyclonev_lift.py against a real Mistral `.bt` decompile.

Does NOT touch the database — this lifter has no board (CLAUDE.md: pluribus
stores no board data without a real board.toml) and load.py's generic pipeline
core (tile loops, pin TSV handling, EFB board semantics) is still
Lattice/Trellis-shaped, so this calls parse_config() / recover_netlist()
directly and reports what came back. It DOES use load.py's classify_lut() /
machxo2_lift.lut_dependence() directly, though — both are now width-generic
(16-char LUT4 or 32-char LUT5, derived from len(init)) and schema.py's `luts`
table now has the 5th-input `e` column + 32-char `init`, so LUT5 cells live
on the same Design.luts list as every other family, not a separate
Design.alm_luts (the schema fit this selftest used to work around).

Also reports package-pin recovery (Design.pads) -- real BGA pin names
recovered from Mistral's trailing `; <pin>` comments, see cyclonev_lift.py's
module docstring PIN RECOVERY section and docs/cyclonev-lifter-status.md.

Usage:
    python3 scripts/cyclonev_lift_selftest.py <path/to/sample.bt>

With no argument, looks for a sample in the default location this session
used to generate one (does not fetch/build it — decoding a bitstream is the
caller's job, see cyclonev_lift.py's module docstring for the mistral-cv
decomp invocation).
"""

import logging
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lifters.cyclonev_lift import CycloneVLift
from load import classify_lut
from lifters import machxo2_lift as mx

DEVICE = "5CEBA4U19C8"


def setup_logging(name):
    os.makedirs("tmp/logs", exist_ok=True)
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(f"tmp/logs/{name}.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def main():
    log = setup_logging("cyclonev_lift_selftest")

    if len(sys.argv) > 1:
        bt_path = sys.argv[1]
    else:
        log.error("usage: cyclonev_lift_selftest.py <path/to/sample.bt>")
        log.error("generate one with: mistral-cv decomp %s "
                   "<bitstream.depack.bin> <out.bt>", DEVICE)
        sys.exit(2)

    if not os.path.isfile(bt_path):
        log.error("not found: %s", bt_path)
        sys.exit(1)

    log.info("device=%s input=%s (%d bytes)", DEVICE, bt_path,
              os.path.getsize(bt_path))

    lift = CycloneVLift(DEVICE)

    log.info("parsing...")
    pc = lift.parse_config(bt_path)
    log.info("parsed: device=%s options=%d arc_lines=%d setting_lines=%d "
              "inverter_lines=%d unparsed_lines=%d",
              pc.device, len(pc.options), pc.n_arc_lines, pc.n_setting_lines,
              pc.n_inverter_lines, pc.n_unparsed_lines)
    if pc.device and pc.device != DEVICE:
        log.warning("'.bt' model line says %s, selftest expected %s",
                    pc.device, DEVICE)

    unparsed_frac = pc.n_unparsed_lines / max(1, (
        pc.n_arc_lines + pc.n_setting_lines + pc.n_inverter_lines
        + pc.n_unparsed_lines))
    if unparsed_frac > 0.01:
        log.warning("%.1f%% of lines were unparsed -- grammar assumption "
                    "may be stale, check _NODE_RE against this .bt's actual "
                    "node syntax", unparsed_frac * 100)

    log.info("recovering netlist...")
    d = lift.recover_netlist(pc)

    log.info("RESULTS")
    log.info("  tile_counts (blocks with >=1 setting line): %s",
              dict(sorted(d.tile_counts.items())))
    log.info("  LABs/MLABs with >=1 configured ALM (nonzero LUT_MASK): %d",
              d.n_alms_configured)
    log.info("  recovered ALM-half LUT5 cells (Design.luts, unified table): %d",
              len(d.luts))
    used = sum(1 for lut in d.luts if lut["z_used"])
    log.info("    of which output is consumed by routing (z_used): %d", used)
    log.info("  recovered registers (Design.ffs): %d", len(d.ffs))
    log.info("  distinct nets (DSU roots named so far): %d", len(d.all_nets))
    log.info("  total routing arcs unioned: %d", d.n_arcs)

    # Exercise load.py's classify_lut()/lut_dependence() on the real LUT5
    # inits -- the same functions every other family's load path calls,
    # now width-generic rather than Cyclone V needing its own copy.
    fn_counts = Counter()
    bad_width = 0
    for lut in d.luts:
        if len(lut["init"]) != 32:
            bad_width += 1
            continue
        deps = mx.lut_dependence(lut["init"])
        lut["deps"] = sorted(deps)
        lut["fn"] = classify_lut(lut["init"])
        fn_counts[lut["fn"]] += 1
    log.info("  classify_lut() width check: %d/%d LUTs have a 32-char init "
              "(%d unexpected width)", len(d.luts) - bad_width, len(d.luts), bad_width)
    log.info("  fn classification counts (top 10): %s",
              fn_counts.most_common(10))

    if d.luts:
        sample = d.luts[0]
        log.info("  sample ALM-half LUT5 cell: %s", sample)
    if d.ffs:
        sample = d.ffs[0]
        log.info("  sample register: %s", sample)

    sources, sinks = lift.arc_endpoint_sets(pc)
    log.info("  distinct arc source nodes: %d, sink nodes: %d",
              len(sources), len(sinks))

    # Smoke-test pad_fabric_node / bels_of don't crash (both are genuinely
    # exercised by a real pipeline caller, even though this selftest has no
    # board/pins to check the result against). pad_fabric_node's pio arg is
    # the block-local bi sub-index (fixed this session -- see its docstring
    # in cyclonev_lift.py), so this now returns a node shape that really
    # appears in the .bt (GPIO.x.y.bi:DATAIN, no .pi), not the old bi=None
    # / pi=pio shape that never matched a real line.
    node = lift.pad_fabric_node(0, 16, 0, "in")
    log.info("  pad_fabric_node(0, 16, 0, 'in') -> %s", node)
    log.info("  bels_of(0, 16) -> %r (expected {}, not implemented this slice)",
              lift.bels_of(0, 16))

    # ---- pin recovery (Design.pads) ----
    # See cyclonev_lift.py's module docstring PIN RECOVERY section for the
    # full edge-case writeup this reporting summarises.
    n_pads = len(d.pads)
    distinct_pins = {p["pin"] for p in d.pads if p["pin"] is not None}
    dir_counts = Counter(p["direction"] for p in d.pads)
    pin_counts = Counter(p["pin"] for p in d.pads if p["pin"] is not None)
    dup_pins = {pin: c for pin, c in pin_counts.items() if c > 1}
    log.info("  PIN RECOVERY:")
    log.info("    GPIO (tile,bi) pads seen in real routing: %d", n_pads)
    log.info("    of which annotated with a real package pin: %d (%.1f%%)",
              d.n_pads_annotated, 100 * d.n_pads_annotated / max(1, n_pads))
    log.info("    unannotated (no ball in Mistral's pin table for this "
              "tile/bank): %d", d.n_pads_unannotated)
    log.info("    distinct package pin names recovered: %d", len(distinct_pins))
    log.info("    pin names appearing on >1 pad row (should be 0 -- "
              "parser bug if not): %d %s", len(dup_pins),
              dict(list(dup_pins.items())[:5]) if dup_pins else "")
    log.info("    direction breakdown: %s", dict(dir_counts))
    log.info("    pads with >1 distinct DATAIN.pi tap (one pin, several "
              "fabric destinations -- net_in keeps only the lowest pi, "
              "see module docstring): %d", d.n_pads_multi_datain_tap)
    log.info("    pads with >1 distinct DATAOUT.pi tap: %d",
              d.n_pads_multi_dataout_tap)
    log.info("    pin comments on non-GPIO (HMC) nodes, out of scope, "
              "not captured: %d", d.n_pin_comments_non_gpio)
    if d.pads:
        annotated_sample = next((p for p in d.pads if p["pin"] is not None), None)
        log.info("    sample annotated pad: %s", annotated_sample)

    pin_recovery_ok = (d.n_pads_annotated > 0 and len(dup_pins) == 0
                        and len(distinct_pins) == d.n_pads_annotated)

    ok = (pc.n_arc_lines > 0 and len(d.luts) > 0
          and bad_width == 0 and unparsed_frac <= 0.01 and pin_recovery_ok)
    log.info("OVERALL %s", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
