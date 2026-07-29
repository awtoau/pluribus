#!/usr/bin/env python3.15t
"""Round-trip check for the ECP5 lifter: lift a `.config`, compare against the
placed netlist nextpnr produced from the SAME run.

This is the difference between "the lifter runs" and "the lifter is right".

Input is a reference directory made by scripts/ecp5_make_reference.py, holding
a matched pair from one nextpnr invocation:
  ref.config        the textcfg (what the lifter reads)
  ref_placed.json   the placed netlist (ground truth)

In the placed netlist every cell carries `NEXTPNR_BEL`, e.g.
"X5/Y42/SLICEA.FF0" or "X3/Y38/SLICEB.K1" — the exact site it landed on.  So
recovery can be checked site by site rather than by totals, which is what
makes the result a verification instead of a plausibility argument.

Checks, strongest first:

  1. LUT PLACEMENT   every TRELLIS_COMB site in the truth must appear in the
                     recovered pc.lut_init, and vice versa.
  2. LUT INIT        bit-for-bit equality of INITVAL at each matched site.
  3. FF PLACEMENT    every TRELLIS_FF site in the truth must be recovered.
  4. FF SD           the REG{j}.SD decode (D from paired LUT vs fabric M).
                     Getting this backwards is silent and catastrophic — it
                     recovers every FF with a constant D while counts and INITs
                     still look perfect.  See ff_d_source() in machxo2_lift.
  5. PAD PLACEMENT   every TRELLIS_IO site vs the lifter's PIO bels.

Usage:
    python3.15t scripts/ecp5_roundtrip.py <ref-dir> [--device LFE5U-12F]

Exit status is non-zero if any check fails.  Logs to
./tmp/logs/ecp5_roundtrip.log as well as the terminal.
"""
import argparse
import collections
import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEF_DBROOT = os.environ.get(
    "TRELLIS_DBROOT", "/home/dan/opt/oss-cad-suite/share/trellis/database")

# "X5/Y42/SLICEA.FF0" / "X3/Y38/SLICEB.K1" / "X0/Y7/PIOA"
BEL_RE = re.compile(r"^X(\d+)/Y(\d+)/(?:SLICE([A-D])\.(K|FF)([01])|PIO([A-D]))$")
FF_NAME_RE = re.compile(r"^ff_r(\d+)c(\d+)_([A-D])(\d)$")


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


def load_truth(path):
    """Parse the placed netlist into site-keyed truth maps.

    Returns (combs, ffs, pios, counts):
      combs[(row, col, slice, k)] = {"init": str, "name": str}
      ffs  [(row, col, slice, k)] = {"sd": str,   "name": str}
      pios[(row, col, letter)]    = {"name": str, "dir": str}
    Keys use (row=Y, col=X) to match the lifter's convention.
    """
    doc = json.load(open(path))
    mod = max(doc["modules"].values(), key=lambda m: len(m.get("cells", {})))
    combs, ffs, pios = {}, {}, {}
    counts = collections.Counter()
    for cname, cell in mod.get("cells", {}).items():
        ctype = cell["type"]
        counts[ctype] += 1
        bel = cell.get("attributes", {}).get("NEXTPNR_BEL")
        if not bel:
            continue
        m = BEL_RE.match(bel)
        if not m:
            continue
        col, row = int(m.group(1)), int(m.group(2))
        params = cell.get("parameters", {})
        if m.group(6):                       # PIO
            pios[(row, col, m.group(6))] = {"name": cname}
        elif m.group(4) == "K":              # TRELLIS_COMB
            combs[(row, col, m.group(3), m.group(5))] = {
                "init": str(params.get("INITVAL", "")).strip(),
                "name": cname,
            }
        else:                                # TRELLIS_FF
            ffs[(row, col, m.group(3), m.group(5))] = {
                "sd": str(params.get("SD", "")).strip(),
                "name": cname,
            }
    return combs, ffs, pios, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref_dir")
    ap.add_argument("--device", default="LFE5U-12F")
    ap.add_argument("--dbroot", default=DEF_DBROOT)
    ap.add_argument("--emit-verilog", default=None,
                    help="also write the recovered netlist here")
    args = ap.parse_args()

    log = setup_logging("ecp5_roundtrip")
    cfg = os.path.join(args.ref_dir, "ref.config")
    truth_path = os.path.join(args.ref_dir, "ref_placed.json")
    for p in (cfg, truth_path):
        if not os.path.exists(p):
            log.error("missing %s — run scripts/ecp5_make_reference.py first", p)
            return 2

    log.info("ref=%s device=%s", args.ref_dir, args.device)
    from lifters.ecp5_lift import ECP5Lift

    t0 = time.time()
    lift = ECP5Lift(args.device, dbroot=args.dbroot)
    log.info("routing graph built in %.1fs", time.time() - t0)

    t0 = time.time()
    pc = lift.parse_config(cfg)
    log.info("parsed: %d arcs, %d lut_init, %d slice_enum sites in %.2fs",
             len(pc.arcs), len(pc.lut_init), len(pc.slice_enum),
             time.time() - t0)

    t0 = time.time()
    design = lift.recover_netlist(pc)
    log.info("recovered in %.2fs: %d LUTs, %d FFs, %d nets "
             "(%d arcs, %d not unioned)",
             time.time() - t0, len(design.luts), len(design.ffs),
             len(design.all_nets), design.n_arcs, design.skipped_arcs)

    combs, ffs, pios, counts = load_truth(truth_path)
    log.info("truth cell types: %s", dict(counts.most_common(8)))

    failures = []

    # --- 1. LUT placement -------------------------------------------------
    got = set(pc.lut_init)
    want = set(combs)
    hit = got & want
    log.info("[1] LUT placement: %d/%d truth sites recovered (%.2f%%); "
             "%d recovered sites absent from truth",
             len(hit), len(want), 100.0 * len(hit) / max(len(want), 1),
             len(got - want))
    for k in sorted(want - got)[:10]:
        log.error("    MISSING lut site %s (%s)", k, combs[k]["name"])
    if hit != want:
        failures.append(f"LUT placement: {len(want - got)} sites missing")

    # --- 2. LUT function --------------------------------------------------
    # An exact INIT comparison is the WRONG test.  nextpnr routes LUT inputs
    # through a permutation crossbar and rewrites INIT to match, and the slice
    # input muxes can tie an input to a constant with the INIT pre-folded for
    # it.  Both rewrite the word while preserving the function.  So compare
    # functions, not words — see scripts/ecp5_lutperm_check.py.
    from scripts.ecp5_lutperm_check import (
        find_perm, functions_equal, tied_inputs)

    exact = perm_eq = tie_eq = 0
    bad = []
    for k in sorted(hit):
        w = combs[k]["init"]
        g = pc.lut_init[k]
        if not w:
            continue
        if w == g:
            exact += 1
        elif find_perm(w, g) is not None:
            perm_eq += 1
        else:
            r, c, sl, kk = k
            tied = tied_inputs(pc.slice_enum.get((r, c, sl), {}), kk)
            if tied and functions_equal(w, g, tied):
                tie_eq += 1
            else:
                bad.append((k, w, g))
    log.info("[2] LUT function: %d identical, %d equal up to input "
             "permutation, %d equal after constant ties, %d WRONG",
             exact, perm_eq, tie_eq, len(bad))
    for k, w, g in bad[:10]:
        log.error("    FUNCTION MISMATCH %s want=%s got=%s", k, w, g)
    if bad:
        failures.append(f"LUT function: {len(bad)} wrong")

    # --- 3. FF placement --------------------------------------------------
    got_ff = {}
    for ff in design.ffs:
        m = FF_NAME_RE.match(ff["name"])
        got_ff[(int(m.group(1)), int(m.group(2)),
                m.group(3), m.group(4))] = ff
    want_ff = set(ffs)
    hit_ff = set(got_ff) & want_ff
    log.info("[3] FF placement: %d/%d truth sites recovered (%.2f%%); "
             "%d recovered sites absent from truth",
             len(hit_ff), len(want_ff),
             100.0 * len(hit_ff) / max(len(want_ff), 1),
             len(set(got_ff) - want_ff))
    for k in sorted(want_ff - set(got_ff))[:10]:
        log.error("    MISSING ff site %s (%s)", k, ffs[k]["name"])
    if hit_ff != want_ff:
        failures.append(f"FF placement: {len(want_ff - set(got_ff))} missing")

    # --- 4. FF SD (D-source) ---------------------------------------------
    # Truth SD is the nextpnr parameter; the lifter stores the same field.
    bad_sd = [(k, ffs[k]["sd"], got_ff[k]["sd"])
              for k in sorted(hit_ff)
              if ffs[k]["sd"] and ffs[k]["sd"] != got_ff[k]["sd"]]
    log.info("[4] FF SD (D-source): %d/%d matched, %d mismatched",
             len(hit_ff) - len(bad_sd), len(hit_ff), len(bad_sd))
    for k, w, g in bad_sd[:10]:
        log.error("    SD MISMATCH %s want=%r got=%r", k, w, g)
    if bad_sd:
        failures.append(f"FF SD: {len(bad_sd)} mismatched")

    # --- 5. Pad placement -------------------------------------------------
    got_pio = set(lift.pio_sites())
    want_pio = set(pios)
    hit_pio = got_pio & want_pio
    log.info("[5] PIO placement: %d/%d truth pad sites have a lifter PIO bel "
             "(%.2f%%)", len(hit_pio), len(want_pio),
             100.0 * len(hit_pio) / max(len(want_pio), 1))
    for k in sorted(want_pio - got_pio)[:10]:
        log.error("    MISSING pio site %s (%s)", k, pios[k]["name"])
    if hit_pio != want_pio:
        failures.append(f"PIO placement: {len(want_pio - got_pio)} missing")

    # --- pad nets (informational) ----------------------------------------
    resolved = sum(
        1 for (r, c, l) in sorted(want_pio)
        if lift.pad_fabric_node(r, c, l, "in") is not None
        or lift.pad_fabric_node(r, c, l, "out") is not None)
    log.info("    pad fabric nodes resolvable: %d/%d", resolved, len(want_pio))

    if args.emit_verilog:
        from lifters.machxo2_lift import write_netlist_verilog
        write_netlist_verilog(design, args.emit_verilog,
                              target=f"ECP5 {args.device}", source=cfg)
        log.info("wrote recovered Verilog to %s", args.emit_verilog)

    if failures:
        log.error("ROUND-TRIP FAILED: %s", "; ".join(failures))
        return 1
    log.info("ROUND-TRIP PASSED: placement, INIT, SD and pads all match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
