#!/usr/bin/env python3
"""Force-decode an unidentified Cyclone V bitstream against all 7 Mistral-
known dies and compare STRUCTURAL PLAUSIBILITY, not just resolved-route
count (awto-dji#3: DJI Lightbridge air-side `m1900`, die unknown; route
count alone climbs with device size on every candidate and never plateaus
-- a known non-discriminating signal, see that issue for the full history
including a retracted resource-capacity-fit method that also failed).

What this adds beyond the existing (exhausted) route-count probe
--------------------------------------------------------------------------
Reuses pluribus's own Cyclone V lifter (lifters/cyclonev_lift.py) to turn
each forced decode into an actual recovered netlist (LUT/FF/pad_map), then
compares:

  1. used LUT:FF ratio       -- RETIRED the raw lut_ff_ratio as a signal
                                 (confounded with resolved-route count: LUTs
                                 are counted unconditionally, FFs only if Q
                                 appears in a resolved route, so the raw
                                 ratio just re-measures route resolution
                                 rate -- demonstrated directly: forcing the
                                 KNOWN-GOOD m2001 sample against the
                                 DEFINITELY-WRONG gt75f produces lut_ff_ratio
                                 2.67, nearly identical to the correct
                                 decode's 2.90, because gt75f's larger
                                 fabric coincidentally resolves more routes.
                                 used_lut_ff_ratio (n_luts_used_by_routing /
                                 n_ffs) gates both sides on resolution and is
                                 reported instead -- not proven valid, just
                                 not this specific confound).
  2. Pad/pin usage            -- sane count + direction mix + 4-edge spread,
                                 vs. degenerate (0, or "every pin", or
                                 one-edge-only).
  3. DSP MODE line diversity  -- `s DSP.*:MODE` lines: do they show real
                                 mixed-width multiplier usage (like the
                                 confirmed-good m2001/e50f sample: 31x M9X9,
                                 10x M18X18P36, 6x M27X27, 6x M18X19_COMBINED)
                                 or silence/uniform noise.
  4. M10K RAM content lines   -- `s RAM.*` presence, as a tile-level-framing
                                 sanity check (not full RAM content analysis).
  5. Configured-ALM fraction  -- nonzero LUT_MASK count vs. die LAB+MLAB
                                 capacity (NOT the retracted "any setting
                                 line present" method -- that is always ~100%
                                 for every die per the retraction in #3).
  6. Global option diversity  -- count of non-default `o OPTION value` lines
                                 in the decompile. A real production design
                                 almost always tunes at least a few chip-wide
                                 options (compression, drive strength, clock
                                 source); zero non-default options on a
                                 forced decode is itself a plausibility
                                 red flag (the option-RAM region decoded to
                                 all-default, consistent with wrong-die
                                 misalignment rather than a real chip image).

m2001 (confirmed e50f, ground-side FPGA) is decoded alongside the 7 die
candidates as a KNOWN-GOOD REFERENCE POINT -- not a target the air-side
decode is expected to match (different design), just a sense-check for
"does this look like a real design produced these numbers at all".

LIFTER ALLOWLIST -- NOT MODIFIED IN cyclonev_lift.py ITSELF
------------------------------------------------------------
lifters/cyclonev_lift.py's CycloneVLift._SUPPORTED_DEVICES deliberately
hard-rejects every device but 5CEBA4U19C8 (e50f) -- the one die with a
human-checked ALM/LAB geometry note (see that module's docstring and
docs/cyclonev-lifter-status.md). This script does NOT loosen that guard
in the shared module (other callers, e.g. load.py/cyclonev_verify_all.py,
rely on it staying strict). Instead it subclasses CycloneVLift locally
(_ForcedDieLift below) with a widened allowlist, used ONLY here.

Rationale for why this is safe to force for a comparison (not a claim the
geometry is validated for the other 6 dies): the ALM-fracturing model (10
ALMs/LAB, each a LUT6 that splits into 2x LUT5) and the pin-coordinate
encoding scheme are both documented in cyclonev_lift.py's own module
docstring as Cyclone-V-FAMILY-WIDE invariants (same fabric, different tile
counts per die), not e50f-specific. All 7 dies share the same u19/484-ball
package per `mistral-cv models` output, so the pin-column-count safety
margin (checked up to U23=23 columns, these are all U19) holds too.

CAVEAT (restated in the final report, not just here): a forced lift that
runs to completion without crashing is NOT independent confirmation the
geometry is correct for dies 2-7 -- only that nothing in Mistral's own
`.bt` output broke this parser's assumptions. A lift CRASH is itself a
data point (stronger negative signal than a low route count -- "even
tile-level framing didn't hold together"), not a bug in this script to
hide; see lift_and_measure()'s try/except.

Usage
-----
    python3.15t scripts/cyclonev_cross_die_plausibility.py \\
        --target /mnt/2tb/git/awto-dji/firmware/unpacked/P3X_m1900/m1900.depack.bin \\
        --target /mnt/2tb/git/awto-dji/firmware/unpacked/P3S_FW_V01.01.0008/m1900_p3s.depack.bin \\
        --reference /mnt/2tb/git/awto-dji/firmware/unpacked/C1_FW_V01.06.0000/m2001.depack.bin

Decodes are sequential by design (awto-dji is a read-only reference input
here; no need for cross-die concurrency -- each decode is independent and
the whole point is comparing results after the fact, not racing them). If
this is ever parallelised, gate on psutil.virtual_memory().percent >= 85
(NOT 50 -- confirmed to stall forever on this host from a permanently-
resident VM; see cyclonev_verify_all.py / cyclonev_db_import_routes.py for
the correct pattern), never mid-decode (Mistral itself is not parallel-
safe per invocation, and 7 simultaneous Mistral processes each wanting
the e50f-to-gt300f RAM range is exactly the prior crash's shape).
"""

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import toolchain
from lifters.cyclonev_lift import CycloneVLift

MISTRAL_CV = Path(toolchain.mistral_cv())

# The 7 dies Mistral ships real fuzzed tile-database data for (awto-dji#3),
# one representative part each, confirmed against `mistral-cv models`
# output this session (all u19/484-ball package). Repeated here rather
# than imported from cyclonev_die_probe.DIES: that module's dict exists for
# an unrelated purpose (Quartus .rbf-size probing); importing it would
# couple this script's constant to a tool this script doesn't use.
DIES = {
    "e50f": "5CEBA4U19C8",
    "gt75f": "5CEBA5U19C8",
    "gt150f": "5CEBA7U19C8",
    "gt300f": "5CEBA9U19C8",
    "gx25f": "5CGXFC3B6U19C7",
    "sx50f": "5CSEBA4U19C8",
    "sx120f": "5CSEBA6U19C7",
}

# Die LAB+MLAB capacity (from `mistral-cv bels <model>`, cross-checked
# against awto-dji#3's retracted-method comment) -- the denominator for a
# DIFFERENT, non-retracted numerator below (nonzero LUT_MASK count, not
# "any setting line present", which that comment showed is always ~100%).
LAB_MLAB_CAPACITY = {
    "e50f": 1364 + 484,
    "gt75f": 2230 + 678,
    "gt150f": 4310 + 1338,
    "gt300f": 8608 + 2748,
    "gx25f": 1055 + 291,
    "sx50f": 1218 + 370,
    "sx120f": 3206 + 985,
}


class _ForcedDieLift(CycloneVLift):
    """CycloneVLift with the device allowlist widened to all 7 Mistral dies
    -- see this module's docstring ("LIFTER ALLOWLIST") for why this is
    done as a local subclass rather than editing cyclonev_lift.py."""
    _SUPPORTED_DEVICES = set(DIES.values())


def setup_logging():
    log_dir = REPO / "tmp" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("cyclonev_cross_die_plausibility")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_dir / "cyclonev_cross_die_plausibility.log")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def decomp(device, rbf_path: Path, out_bt: Path, log, timeout_s):
    """Run `mistral-cv decomp <device> <rbf> <out.bt>`.

    Timeout rationale: e50f's real m2001 decomp (359,956-line .bt) ran in
    well under 60s on this 30-core/62GB host this session. gt300f's
    LAB+MLAB capacity is ~6.3x e50f's, so 600s (default) gives >6x margin
    over a linear scale-up of that measured baseline -- comfortably over
    the 1.25x rule for a measured-and-scaled bound. On expiry: logs
    device/elapsed/limit and returns None, so one slow die doesn't hang
    the whole 7-die sweep.
    """
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [str(MISTRAL_CV), "decomp", device, str(rbf_path), str(out_bt)],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        log.error("decomp TIMEOUT device=%s limit=%ds elapsed=%.1fs -- "
                   "killed, treating as failed decode for this die",
                   device, timeout_s, elapsed)
        return None
    elapsed = time.monotonic() - t0
    if result.returncode != 0:
        log.warning("decomp FAILED device=%s rc=%d elapsed=%.1fs stderr_tail=%s",
                    device, result.returncode, elapsed, result.stderr[-500:])
        return None
    log.info("decomp OK device=%s elapsed=%.1fs -> %s (%d bytes)",
              device, elapsed, out_bt, out_bt.stat().st_size if out_bt.exists() else 0)
    return out_bt


_DSP_MODE_RE = re.compile(r"^s DSP\.\S+:MODE(?:\.\d+)?\s+(\S+)")


def bt_record_counts(bt_path: Path):
    """Raw text scan for record types the lifter does not model (DSP MODE,
    M10K RAM content) -- same approach the original m2001 analysis used
    (m2001-decomp-findings.md), kept as a raw scan rather than extending
    the lifter, since DSP/M10K content recovery is explicitly out of scope
    for CycloneVLift (its own module docstring). Also counts non-default
    global `o` option lines -- signal #6 in the module docstring."""
    dsp_modes = Counter()
    n_dsp_lines = 0
    n_ram_lines = 0
    n_option_lines = 0
    n_lines = 0
    with open(bt_path, "r", errors="replace") as f:
        for line in f:
            n_lines += 1
            if line.startswith("s DSP."):
                n_dsp_lines += 1
                m = _DSP_MODE_RE.match(line)
                if m:
                    dsp_modes[m.group(1)] += 1
            elif line.startswith("s RAM."):
                n_ram_lines += 1
            elif line.startswith("o "):
                n_option_lines += 1
    return {
        "n_lines": n_lines,
        "n_dsp_setting_lines": n_dsp_lines,
        "n_ram_setting_lines": n_ram_lines,
        "n_option_lines": n_option_lines,
        "dsp_modes": dict(dsp_modes.most_common()),
    }


def lift_and_measure(die, device, bt_path: Path, log):
    """Run _ForcedDieLift on one .bt, return a plausibility-signal dict.
    Any exception during lift is caught and reported as a structural
    failure (tile-level framing didn't even hold together), not raised --
    a crash here is itself a data point (per this module's CAVEAT), not a
    script bug to hide."""
    raw = bt_record_counts(bt_path)
    try:
        lift = _ForcedDieLift(device)
        t0 = time.monotonic()
        pc = lift.parse_config(str(bt_path))
        d = lift.recover_netlist(pc)
        elapsed = time.monotonic() - t0
    except Exception as exc:
        log.error("LIFT CRASHED die=%s device=%s: %r", die, device, exc)
        return {"die": die, "device": device, "lift_crashed": True,
                "lift_error": repr(exc), **raw}

    n_luts = len(d.luts)
    n_luts_used = sum(1 for lut in d.luts if lut["z_used"])
    n_ffs = len(d.ffs)
    lut_ff_ratio = (n_luts / n_ffs) if n_ffs else None
    used_lut_ff_ratio = (n_luts_used / n_ffs) if n_ffs else None

    n_pads = len(d.pads)
    distinct_pins = {p["pin"] for p in d.pads if p["pin"] is not None}
    dir_counts = Counter(p["direction"] for p in d.pads)

    cap = LAB_MLAB_CAPACITY.get(die)
    configured_frac = (d.n_alms_configured / cap) if cap else None

    result = {
        "die": die, "device": device, "lift_crashed": False,
        "parse": {
            "n_arc_lines": pc.n_arc_lines, "n_setting_lines": pc.n_setting_lines,
            "n_inverter_lines": pc.n_inverter_lines,
            "n_unparsed_lines": pc.n_unparsed_lines,
        },
        "n_luts": n_luts, "n_luts_used_by_routing": n_luts_used,
        "n_ffs": n_ffs,
        "lut_ff_ratio": round(lut_ff_ratio, 3) if lut_ff_ratio else None,
        "used_lut_ff_ratio": round(used_lut_ff_ratio, 3) if used_lut_ff_ratio else None,
        "n_alms_configured": d.n_alms_configured,
        "lab_mlab_capacity": cap,
        "configured_alm_fraction": round(configured_frac, 4) if configured_frac else None,
        "n_distinct_nets": len(d.all_nets),
        "n_arcs_unioned": d.n_arcs,
        "pads": {
            "n_pads": n_pads,
            "n_distinct_pins": len(distinct_pins),
            "direction_breakdown": dict(dir_counts),
        },
        "lift_elapsed_s": round(elapsed, 1),
        **raw,
    }
    log.info("LIFT die=%s luts=%d ffs=%d lut:ff=%s configured_alm_frac=%s "
              "pads=%d distinct_pins=%d options=%d dsp_lines=%d dsp_modes=%s ram_lines=%d",
              die, n_luts, n_ffs, result["lut_ff_ratio"],
              result["configured_alm_fraction"], n_pads, len(distinct_pins),
              raw["n_option_lines"], raw["n_dsp_setting_lines"], raw["dsp_modes"],
              raw["n_ram_setting_lines"])
    return result


def run_one(label, rbf_path: Path, work_dir: Path, log, decomp_timeout_s,
            devices=DIES):
    """Force-decode `rbf_path` against every die in `devices`, lift each,
    return {die: measurement_dict}."""
    out = {}
    for die, device in devices.items():
        bt_path = work_dir / f"{label}__{die}.bt"
        log.info("=== %s vs %s (%s) ===", label, die, device)
        if bt_path.exists() and bt_path.stat().st_size > 0:
            log.info("reusing existing decomp %s", bt_path)
        else:
            if decomp(device, rbf_path, bt_path, log, decomp_timeout_s) is None:
                out[die] = {"die": die, "device": device, "decomp_failed": True}
                continue
        out[die] = lift_and_measure(die, device, bt_path, log)
    return out


def print_comparison_table(label, per_die, log):
    print(f"\n=== {label} ===")
    print("NOTE: raw lut_ff_ratio is RETIRED as a plausibility signal (confounded")
    print("with resolved-route count -- n_luts is unconditional, n_ffs is gated on")
    print("Q appearing in a RESOLVED route, so the ratio just re-measures route")
    print("resolution rate under another name; a definitely-wrong larger die can")
    print("resolve MORE routes than the correct die and produce a near-identical")
    print("ratio, verified directly: m2001/known-good e50f=2.90 vs. m2001 forced")
    print("against the definitely-wrong gt75f=2.67. used_lut_ff_ratio below divides")
    print("n_luts_USED-by-routing by n_ffs -- both sides now gated on route")
    print("resolution, so it is no longer comparing a conditional count against an")
    print("unconditional one. Still not a proven-valid signal, just no longer the")
    print("specific confound found and demonstrated this session.")
    hdr = (f"{'die':8s} {'LUTs':>7s} {'FFs':>7s} {'usedLUT:FF':>10s} "
           f"{'cfgALM%':>8s} {'pads':>5s} {'pins':>5s} {'opts':>5s} {'dsp_md':>7s} "
           f"{'ram_ln':>7s} {'arcs':>8s} {'unparsed%':>9s}")
    print(hdr)
    for die in DIES:
        m = per_die.get(die, {})
        if m.get("decomp_failed"):
            print(f"{die:8s} DECOMP FAILED/TIMEOUT")
            continue
        if m.get("lift_crashed"):
            print(f"{die:8s} LIFT CRASHED: {m.get('lift_error')}")
            continue
        p = m.get("parse", {})
        total_lines = (p.get("n_arc_lines", 0) + p.get("n_setting_lines", 0)
                        + p.get("n_inverter_lines", 0) + p.get("n_unparsed_lines", 0))
        unparsed_pct = (100 * p.get("n_unparsed_lines", 0) / total_lines) if total_lines else 0
        dsp_modes_str = ",".join(f"{k}:{v}" for k, v in m.get("dsp_modes", {}).items()) or "-"
        print(f"{die:8s} {m.get('n_luts', '-'):>7} {m.get('n_ffs', '-'):>7} "
              f"{str(m.get('used_lut_ff_ratio', '-')):>10} "
              f"{str(round((m.get('configured_alm_fraction') or 0) * 100, 1)):>8} "
              f"{m.get('pads', {}).get('n_pads', '-'):>5} "
              f"{m.get('pads', {}).get('n_distinct_pins', '-'):>5} "
              f"{m.get('n_option_lines', '-'):>5} "
              f"{dsp_modes_str:>7} "
              f"{m.get('n_ram_setting_lines', '-'):>7} "
              f"{m.get('n_arcs_unioned', '-'):>8} "
              f"{unparsed_pct:>8.2f}%")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", action="append", required=True,
                     help="depacked unknown bitstream (repeatable, e.g. P3X and P3S m1900 samples)")
    ap.add_argument("--reference", default=None,
                     help="depacked KNOWN-GOOD bitstream for sanity reference (e.g. m2001)")
    ap.add_argument("--reference-device", default="5CEBA4U19C8")
    ap.add_argument("--work-dir", type=Path,
                     default=REPO / "tmp" / "cyclonev_cross_die")
    ap.add_argument("--decomp-timeout-s", type=int, default=600,
                     help="per-die decomp timeout (default 600s, see decomp()'s docstring)")
    args = ap.parse_args()

    log = setup_logging()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    all_results = {}

    if args.reference:
        ref_path = Path(args.reference)
        log.info("Decoding REFERENCE (known-good) %s against its own confirmed die", ref_path)
        ref_die = next(d for d, p in DIES.items() if p == args.reference_device)
        ref_result = run_one("reference", ref_path, args.work_dir, log,
                              args.decomp_timeout_s,
                              devices={ref_die: args.reference_device})
        all_results["reference"] = ref_result
        print_comparison_table(f"REFERENCE {ref_path.name} (confirmed {ref_die})",
                                ref_result, log)

    for target in args.target:
        tpath = Path(target)
        label = tpath.stem
        log.info("Force-decoding TARGET %s against all 7 dies", tpath)
        per_die = run_one(label, tpath, args.work_dir, log, args.decomp_timeout_s)
        all_results[label] = per_die
        print_comparison_table(f"TARGET {tpath.name} (die unknown, forced vs all 7)",
                                per_die, log)

    out_json = args.work_dir / "results.json"
    out_json.write_text(json.dumps(all_results, indent=2))
    log.info("Full results written to %s", out_json)


if __name__ == "__main__":
    main()
