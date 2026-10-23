#!/usr/bin/env python3
"""Fuzz Cyclone V DSP block operational-mode encoding (issue: DSP mode ground
truth — follow-on to cyclonev_die_probe.py's die-identification probe).

Mistral decompiles Cyclone V DSP tiles to named `s DSP.*:MODE` settings
(M9X9/M18X18P36/M27X27/... — confirmed present in a real unknown design's
decompile, awto-dji's m2001) but Mistral itself does NOT decode what those
settings mean operationally (confirmed by reading mistral-cv's own source:
"TODO: everything" for DSP mux usage/port mapping). This script builds the
other half: compile KNOWN Quartus designs, each inferring exactly ONE DSP
operation, and record which DSP.MODE value and DSP.* settings each one
produces — real ground truth, not a guess from a string that looks right.

Same proven flow as scripts/cyclonev_die_probe.py:
    quartus_map -> quartus_fit -> quartus_asm -> quartus_cpf -c (.rbf)
then new for this script:
    mistral-cv decomp <model> <rbf> <bt>  -> extract `s DSP.*` lines

Device: 5CEBA4U19C8 (e50f/e50b) -- same die as the real DJI m2001 ground FPGA
this is meant to apply to (docs/cyclonev-lifter-status.md).

Usage:
    python3 scripts/cyclonev_dsp_fuzz.py              # all designs
    python3 scripts/cyclonev_dsp_fuzz.py --only mult9x9
    python3 scripts/cyclonev_dsp_fuzz.py --keep        # keep quartus/mistral work dirs

Output:
    tmp/logs/cyclonev_dsp_fuzz.log   -- full run log
    tmp/cyclonev_dsp_fuzz/<design>/  -- quartus project + .bt decompile (gitignored, tmp/)
    tmp/cyclonev_dsp_fuzz/mapping.json -- the mapping table (design -> DSP.* settings)
"""
import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard
import toolchain

# Resolved via the shared toolchain module (env var, then conventional
# install globs, newest version wins) rather than a hardcoded path -- see
# scripts/toolchain.py:quartus_bin()/mistral_cv() and
# docs/cyclonev-verification.md for re-running against a different install.
QUARTUS_BIN = Path(toolchain.quartus_bin())
MISTRAL_CV = Path(toolchain.mistral_cv())
DEVICE = "5CEBA4U19C8"          # e50f/e50b -- same die as cyclonev_die_probe.py/DJI m2001
WORK_DIR = REPO / "tmp" / "cyclonev_dsp_fuzz"
LOG_PATH = REPO / "tmp" / "logs" / "cyclonev_dsp_fuzz.log"

# ── test designs ─────────────────────────────────────────────────────────────
# Each instantiates ONE multiply/DSP operation and nothing else, so the
# resulting bitstream has exactly one configured DSP tile to diff. Plain
# Verilog (`*`), not megafunction/IP instantiation -- quartus_map's synthesis
# report (checked per-design below) confirms DSP inference without needing
# qmegawiz, which is a slower, more failure-prone Tcl-driven flow for designs
# this simple.

DESIGNS = {
    "mult9x9": {
        "desc": "9x9 signed multiply, registered output -> expect M9X9",
        "verilog": """module mult9x9(input clk, input signed [8:0] a, input signed [8:0] b,
  output reg signed [17:0] p);
  always @(posedge clk) p <= a * b;
endmodule
""",
    },
    "mult18x18": {
        "desc": "18x18 signed multiply, registered output -> expect M18X18",
        "verilog": """module mult18x18(input clk, input signed [17:0] a, input signed [17:0] b,
  output reg signed [35:0] p);
  always @(posedge clk) p <= a * b;
endmodule
""",
    },
    "mult27x27": {
        "desc": "27x27 signed multiply, registered output -> expect M27X27 "
                 "or ganged multi-block (checked, not assumed)",
        "verilog": """module mult27x27(input clk, input signed [26:0] a, input signed [26:0] b,
  output reg signed [53:0] p);
  always @(posedge clk) p <= a * b;
endmodule
""",
    },
    "multacc18x18": {
        "desc": "18x18 multiply-accumulate -> expect systolic/accumulator mode",
        "verilog": """module multacc18x18(input clk, input rst,
  input signed [17:0] a, input signed [17:0] b,
  output reg signed [43:0] acc);
  always @(posedge clk)
    if (rst) acc <= 0;
    else acc <= acc + (a * b);
endmodule
""",
    },
}

_DSP_SETTING_RE = re.compile(r"^s\s+(DSP\.\S+)\s+(.+?)\s*(?:;.*)?$")


def setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cyclonev_dsp_fuzz")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_PATH)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def run(cmd, cwd, logger, timeout=180):
    """timeout=180s: 1.25x the ~140s worst-case quartus_fit seen on this
    design class in cyclonev_die_probe.py's run this session (near-empty
    designs on e50f); quartus_asm/map/cpf are all faster than fit."""
    logger.info("+ %s", " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        logger.error("FAILED (rc=%d): %s\n--- stdout tail ---\n%s\n--- stderr tail ---\n%s",
                      result.returncode, " ".join(str(c) for c in cmd),
                      result.stdout[-3000:], result.stderr[-1500:])
        return None
    return result.stdout


def check_dsp_inferred(map_report_text: str, logger, name: str) -> bool:
    """quartus_map's .map.rpt names inferred DSP primitives explicitly under
    'Full Hierarchy' / resource-usage sections. We check the raw report text
    (read after quartus_map) for the family's DSP megafunction names rather
    than assuming synthesis picked DSP over soft logic for a small multiply --
    Quartus can map a narrow multiply to LUTs/ALMs instead if told to, or if
    synthesis settings disfavour the DSP block."""
    markers = ("mult", "dsp", "altera_mult_add", "LAB_CELL_OUT")  # fallback, replaced below
    found = any(m in map_report_text.lower() for m in ("dsp", "mult_add", "altmult"))
    logger.info("%s: DSP-inference marker present in map report: %s", name, found)
    return found


def quartus_compile_design(name, spec, work_dir: Path, logger):
    """Producer-side half: quartus_map -> fit -> asm -> cpf only, no
    mistral-cv decompile.  Split out of the old compile_design() (which
    used to do both halves in one call) so a multi-design harness can run
    the slow Quartus half across a wide compile pool while a smaller pool
    drains the fast decompile+extract half -- see cyclonev_verify_all.py.
    Returns a dict with 'rbf'/'dsp_inferred' or None on failure.
    """
    d = work_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.v").write_text(spec["verilog"])
    (d / f"{name}.qsf").write_text(
        f'set_global_assignment -name FAMILY "Cyclone V"\n'
        f'set_global_assignment -name DEVICE {DEVICE}\n'
        f'set_global_assignment -name TOP_LEVEL_ENTITY {name}\n'
        f'set_global_assignment -name VERILOG_FILE {name}.v\n'
        # Let synthesis infer DSP naturally; don't force DSP_BLOCK_BALANCING
        # or disable the DSP block -- that's the point of this experiment.
    )

    heavy_guard.wait_available(logger, name)
    logger.info("=== %s: %s ===", name, spec["desc"])

    if run([str(QUARTUS_BIN / "quartus_map"), name,
            "--family=Cyclone V", f"--part={DEVICE}"], d, logger) is None:
        return None
    map_rpt = d / f"{name}.map.rpt"
    map_text = map_rpt.read_text(errors="replace") if map_rpt.exists() else ""
    dsp_inferred = check_dsp_inferred(map_text, logger, name)

    if run([str(QUARTUS_BIN / "quartus_fit"), name], d, logger) is None:
        return None
    if run([str(QUARTUS_BIN / "quartus_asm"), name], d, logger) is None:
        return None

    sof = d / f"{name}.sof"
    rbf = d / f"{name}.rbf"
    if run([str(QUARTUS_BIN / "quartus_cpf"), "-c", str(sof), str(rbf)], d, logger) is None:
        return None

    return {"name": name, "desc": spec["desc"], "dir": d, "rbf": rbf,
            "dsp_inferred_in_map_report": dsp_inferred}


def decompile_and_extract_design(compiled, logger):
    """Consumer-side half: mistral-cv decomp + extract_dsp_settings on an
    already-compiled design (the dict quartus_compile_design() returned).
    Returns the same result shape compile_design() used to return in one
    shot, or None on failure.
    """
    name, d, rbf = compiled["name"], compiled["dir"], compiled["rbf"]
    bt = d / f"{name}.bt"
    decomp_out = run([str(MISTRAL_CV), "decomp", DEVICE, str(rbf), str(bt)], d, logger)
    if decomp_out is None:
        return None
    if not bt.exists():
        logger.error("%s: mistral-cv decomp produced no .bt file", name)
        return None

    dsp_settings = extract_dsp_settings(bt, logger, name)

    return {
        "name": name,
        "desc": compiled["desc"],
        "dsp_inferred_in_map_report": compiled["dsp_inferred_in_map_report"],
        "bt_path": str(bt),
        "dsp_settings": dsp_settings,
    }


def compile_design(name, spec, work_dir: Path, logger):
    """Original single-call entry point (compile + decompile), kept for the
    standalone CLI below -- now a thin wrapper over the two split halves."""
    compiled = quartus_compile_design(name, spec, work_dir, logger)
    if compiled is None:
        return None
    return decompile_and_extract_design(compiled, logger)


def extract_dsp_settings(bt_path: Path, logger, name: str) -> dict:
    """Pull every `s DSP.*` line, grouped by DSP tile (x,y). A design this
    small should only have ONE DSP tile with non-default settings -- flag
    (not silently pick) if more than one tile shows up, since that would mean
    this design isn't as minimal as intended."""
    by_tile = {}
    with bt_path.open(errors="replace") as f:
        for line in f:
            m = _DSP_SETTING_RE.match(line.rstrip("\n"))
            if not m:
                continue
            node, value = m.group(1), m.group(2)
            # node looks like DSP.x.y[.bi][:PORT...] -- tile key is DSP.x.y
            tile_m = re.match(r"(DSP\.\d+\.\d+)", node)
            tile = tile_m.group(1) if tile_m else node
            by_tile.setdefault(tile, {})[node] = value

    n_tiles = len(by_tile)
    logger.info("%s: %d DSP tile(s) with non-default settings", name, n_tiles)
    if n_tiles == 0:
        logger.warning("%s: NO DSP.* settings found in decompile -- synthesis "
                        "likely did not use a DSP block for this design (check "
                        "dsp_inferred_in_map_report / the .map.rpt directly)", name)
    elif n_tiles > 1:
        logger.warning("%s: %d DSP tiles configured, expected 1 -- design may "
                        "not be as minimal as intended, inspect all tiles below", name)

    for tile, settings in sorted(by_tile.items()):
        logger.info("%s: tile %s:", name, tile)
        for node, value in sorted(settings.items()):
            logger.info("%s:   %s = %s", name, node, value)

    return by_tile


def mode_values(dsp_settings: dict) -> list:
    """Pull out just the MODE setting value(s) across all tiles, for the
    quick summary table."""
    modes = []
    for tile, settings in dsp_settings.items():
        for node, value in settings.items():
            if node.endswith(":MODE") or ".MODE" in node.split(":")[-1:]:
                modes.append((tile, node, value))
            elif node.split(":")[-1].startswith("MODE"):
                modes.append((tile, node, value))
    return modes


def main():
    with heavy_guard.heavy_lock("cyclonev_dsp_fuzz", heavy_guard.stdout_log()):
        _main()


def _main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=None,
                     help="subset of design names to run (default: all)")
    ap.add_argument("--keep", action="store_true",
                     help="keep quartus/mistral work dirs (default: kept regardless, "
                          "tmp/ is gitignored -- flag exists for symmetry with other "
                          "fuzz scripts, no separate cleanup is done either way)")
    args = ap.parse_args()

    logger = setup_logging()
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    names = args.only if args.only else list(DESIGNS.keys())
    unknown = [n for n in names if n not in DESIGNS]
    if unknown:
        logger.error("unknown design name(s): %s (known: %s)",
                      unknown, list(DESIGNS.keys()))
        sys.exit(2)

    results = {}
    for name in names:
        res = compile_design(name, DESIGNS[name], WORK_DIR, logger)
        if res is None:
            logger.error("%s: FAILED, skipping", name)
            continue
        results[name] = res

    out_path = WORK_DIR / "mapping.json"
    out_path.write_text(json.dumps(results, indent=2))
    logger.info("Wrote mapping table: %s", out_path)

    print("\n=== Cyclone V DSP mode mapping (device=%s) ===" % DEVICE)
    for name, res in results.items():
        modes = mode_values(res["dsp_settings"])
        mode_str = ", ".join(f"{node}={value}" for _, node, value in modes) or "(none found)"
        print(f"{name:16s} dsp_inferred={res['dsp_inferred_in_map_report']!s:5s} "
              f"tiles={len(res['dsp_settings'])}  {mode_str}")
    print(f"\nFull settings: {out_path}")
    print(f"Log: {LOG_PATH}")

    n_ok = sum(1 for r in results.values() if r["dsp_settings"])
    logger.info("Done. %d/%d designs compiled with >=1 DSP.* setting recovered.",
                n_ok, len(names))
    sys.exit(0 if n_ok == len(names) else 1)


if __name__ == "__main__":
    main()
