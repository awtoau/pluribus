#!/usr/bin/env python3
"""
parse_results.py — Diff fuzz .config files against baseline, extract changed bits.

Usage:
    cd /mnt/2tb/git/awto-2000
    python3 fpga/diamond/fuzz/scripts/parse_results.py [--baseline PATH]

Inputs:
    fuzz/baseline/empty.config          — empty design bitstream (reference)
    fuzz/results/<target>/<target>.config — per-target bitstream from ecpunpack

Outputs:
    fuzz/results/summary.txt            — changed-bit counts per target
    fuzz/results/<primitive>_bits.txt   — grouped by primitive family

.config format from ecpunpack:
    .tile <name>
    .config
    <frame>: <64-bit hex word> <64-bit hex word> ...
    (frames are rows, bit position within each word is the column)

This parser extracts which tiles and bits differ from the baseline,
groups results by primitive family, and produces human-readable reports.
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# ── Repo layout ──────────────────────────────────────────────────────────────

ROOT        = Path(__file__).resolve().parents[4]
FUZZ_DIR    = ROOT / "fpga" / "diamond" / "fuzz"
TARGETS_DIR = FUZZ_DIR / "targets"
RESULTS_DIR = FUZZ_DIR / "results"
BASELINE    = FUZZ_DIR / "baseline" / "empty.config"

# ── .config parser ────────────────────────────────────────────────────────────

def parse_config(text: str) -> dict[str, dict[int, int]]:
    """Parse ecpunpack .config text.

    Returns: { tile_name: { frame_idx: word_value, ... }, ... }

    The .config format has sections introduced by:
        .tile R<row>C<col>_<type>
        .config
        <frame>: <hex> <hex> ...
    Frame indices are the row/frame number; each hex word is a 64-bit column word.
    We flatten the words into a single integer per frame for XOR diffing.
    """
    tiles: dict[str, dict[int, int]] = {}
    current_tile = None
    in_config    = False
    frame_idx    = 0

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # New tile section
        m = re.match(r"^\.tile\s+(\S+)", line)
        if m:
            current_tile = m.group(1)
            tiles.setdefault(current_tile, {})
            in_config = False
            continue

        if line == ".config":
            in_config = True
            frame_idx = 0
            continue

        # Frame data: "<idx>: <hex> <hex> ..."  OR just "<hex> <hex> ..."
        if in_config and current_tile:
            # Strip optional leading "<n>:" index
            data = re.sub(r"^\d+:\s*", "", line)
            # Each space-separated token is one 64-bit word
            words = data.split()
            if not words:
                continue
            # Combine all words into a single wide integer (word0 is low bits)
            combined = 0
            for i, w in enumerate(words):
                try:
                    combined |= int(w, 16) << (64 * i)
                except ValueError:
                    continue
            tiles[current_tile][frame_idx] = combined
            frame_idx += 1
            continue

    return tiles


def diff_configs(base: dict, fuzz: dict) -> dict[str, list[tuple[int, int]]]:
    """Return changed bits: { tile: [(frame, bit), ...] }.

    Compares every tile+frame in fuzz against base.
    Only tiles/frames that are present in at least one of base/fuzz are considered.
    """
    changed: dict[str, list[tuple[int, int]]] = {}

    all_tiles = set(base) | set(fuzz)
    for tile in sorted(all_tiles):
        base_frames = base.get(tile, {})
        fuzz_frames = fuzz.get(tile, {})
        all_frames  = set(base_frames) | set(fuzz_frames)
        bits_changed = []
        for frame in sorted(all_frames):
            bval = base_frames.get(frame, 0)
            fval = fuzz_frames.get(frame, 0)
            diff = bval ^ fval
            if diff:
                # Extract individual bit positions
                bit = 0
                while diff:
                    if diff & 1:
                        bits_changed.append((frame, bit))
                    diff >>= 1
                    bit  += 1
        if bits_changed:
            changed[tile] = bits_changed
    return changed


# ── Primitive family grouping ─────────────────────────────────────────────────

# Map target-name prefix → family name for grouping output
FAMILIES = {
    "iddrxe":      "IOLOGIC_DDR_INPUT",
    "iddrx2e":     "IOLOGIC_DDR_INPUT",
    "iddrx4b":     "IOLOGIC_DDR_INPUT",
    "iddrdqsx1a":  "IOLOGIC_DDR_INPUT",
    "iddrx71a":    "IOLOGIC_DDR_INPUT",
    "oddrxe":      "IOLOGIC_DDR_OUTPUT",
    "oddrx2e":     "IOLOGIC_DDR_OUTPUT",
    "oddrx4b":     "IOLOGIC_DDR_OUTPUT",
    "oddrdqsx1a":  "IOLOGIC_DDR_OUTPUT",
    "oddrx71a":    "IOLOGIC_DDR_OUTPUT",
    "tddra":       "IOLOGIC_DDR_TRISTATE",
    "ifs1p3bx":    "IOLOGIC_INPUT_FF",
    "ifs1p3dx":    "IOLOGIC_INPUT_FF",
    "ifs1p3ix":    "IOLOGIC_INPUT_FF",
    "ifs1p3jx":    "IOLOGIC_INPUT_FF",
    "ifs1s1b":     "IOLOGIC_INPUT_FF",
    "ifs1s1d":     "IOLOGIC_INPUT_FF",
    "ifs1s1i":     "IOLOGIC_INPUT_FF",
    "ifs1s1j":     "IOLOGIC_INPUT_FF",
    "ofs1p3bx":    "IOLOGIC_OUTPUT_FF",
    "ofs1p3dx":    "IOLOGIC_OUTPUT_FF",
    "ofs1p3ix":    "IOLOGIC_OUTPUT_FF",
    "ofs1p3jx":    "IOLOGIC_OUTPUT_FF",
    "dqsbufh":     "IOLOGIC_DQS",
    "dqsdllc":     "IOLOGIC_DQS",
    "dlldelc":     "IOLOGIC_DELAY",
    "delaye":      "IOLOGIC_DELAY",
    "delayd":      "IOLOGIC_DELAY",
    "bb":          "IO_BUFFER",
    "bbpd":        "IO_BUFFER",
    "bbpu":        "IO_BUFFER",
    "bbw":         "IO_BUFFER",
    "ib":          "IO_BUFFER",
    "ibpd":        "IO_BUFFER",
    "ibpu":        "IO_BUFFER",
    "ob":          "IO_BUFFER",
    "obz":         "IO_BUFFER",
    "obzpu":       "IO_BUFFER",
    "obco":        "IO_BUFFER",
    "ilvds":       "IO_BUFFER_LVDS",
    "olvds":       "IO_BUFFER_LVDS",
    "lvdsob":      "IO_BUFFER_LVDS",
    "inrdb":       "IO_BUFFER",
    "bcinrd":      "IO_BANK",
    "bclvdso":     "IO_BANK",
    "eclksynca":   "CLOCK",
    "eclkbridgecs":"CLOCK",
    "clkdivc":     "CLOCK",
    "clkfbbufa":   "CLOCK",
    "dcca":        "CLOCK",
    "dcma":        "CLOCK",
    "pllrefcs":    "CLOCK",
    "ehxpllj":     "PLL",
    "osch":        "OSCILLATOR",
    "dp8kc":       "EBR",
    "pdpw8kc":     "EBR",
    "sp8kc":       "EBR",
    "fifo8kb":     "EBR",
    "dpr16x4c":    "DISTRIBUTED_RAM",
    "spr16x4c":    "DISTRIBUTED_RAM",
    "rom16x1a":    "ROM",
    "rom32x1a":    "ROM",
    "rom64x1a":    "ROM",
    "rom128x1a":   "ROM",
    "rom256x1a":   "ROM",
    "efb":         "EFB",
    "jtagf":       "JTAG",
    "gsr":         "GLOBAL_CTRL",
    "sgsr":        "GLOBAL_CTRL",
    "tsall":       "GLOBAL_CTRL",
    "pur":         "GLOBAL_CTRL",
    "pg":          "GLOBAL_CTRL",
    "pcntr":       "POWER_CTRL",
    "start":       "CONFIG",
    "sedfa":       "SED",
    "sedfb":       "SED",
    "ccu2d":       "CARRY",
    "syn_useioff": "HIGHLEVEL_SYNTH",
    "syn_keep":    "HIGHLEVEL_SYNTH",
    "inferred_ddr":"HIGHLEVEL_INFERRED",
    "inferred_bram":"HIGHLEVEL_INFERRED",
    "inferred_shreg":"HIGHLEVEL_INFERRED",
    "efb_spi":     "EFB",
    "efb_i2c":     "EFB",
    "efb_tc":      "EFB",
    "efb_ufm":     "EFB",
    "efb_all":     "EFB",
}


def get_family(target_name: str) -> str:
    """Map target name to primitive family."""
    lower = target_name.lower()
    # Try longest prefix match
    best_prefix = ""
    best_family = "OTHER"
    for prefix, family in FAMILIES.items():
        if lower.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
            best_family = family
    return best_family


# ── Location cross-check ──────────────────────────────────────────────────────

def extract_bank(target_name: str) -> str | None:
    """Extract bank label from target name (e.g. 'iddrxe_bank0' → 'bank0')."""
    m = re.search(r"(bank\d+|left|right|top|bottom)", target_name.lower())
    return m.group(1) if m else None


def cross_check_banks(family_results: dict[str, dict]) -> list[str]:
    """
    For each primitive, compare changed bits across bank variants.
    If the same primitive at different banks produces the same *types* of tiles
    but different tile addresses, that confirms the encoding is location-independent.

    Returns list of text lines describing consistency findings.
    """
    lines = []
    # Group by primitive base name (strip _bank0/_bank1 suffix)
    prim_variants: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for target_name, diff_data in family_results.items():
        base = re.sub(r"_(bank\d+|left|right|top|bottom)$", "", target_name.lower())
        bank = extract_bank(target_name) or "unknown"
        prim_variants[base].append((bank, diff_data))

    for prim_base, variants in sorted(prim_variants.items()):
        if len(variants) < 2:
            continue   # can't cross-check with only one location

        tile_type_sets = []
        for bank, diff_data in variants:
            # Extract tile type names (strip address prefix like R2C5_)
            types = set()
            for tile in diff_data:
                m = re.match(r"^R\d+C\d+_(.+)$", tile)
                types.add(m.group(1) if m else tile)
            tile_type_sets.append((bank, types))

        # Check if all variants change the same tile types
        all_types = tile_type_sets[0][1]
        consistent = all(ts == all_types for _, ts in tile_type_sets)
        if consistent:
            lines.append(
                f"  CONSISTENT  {prim_base:<30s}  tile types match across "
                + ", ".join(b for b, _ in tile_type_sets)
                + f"  [{', '.join(sorted(all_types))}]"
            )
        else:
            lines.append(f"  INCONSISTENT  {prim_base}:")
            for bank, types in tile_type_sets:
                lines.append(f"    {bank}: {sorted(types)}")

    return lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", default=str(BASELINE),
                    help=f"Path to baseline (empty design) .config  [default: {BASELINE}]")
    ap.add_argument("--results-dir", default=str(RESULTS_DIR),
                    help="Directory containing per-target result subdirs")
    args = ap.parse_args()

    baseline_path = Path(args.baseline)
    results_dir   = Path(args.results_dir)

    if not baseline_path.exists():
        sys.exit(
            f"Baseline not found: {baseline_path}\n"
            "Run the empty design through Diamond first and copy the .config here:\n"
            f"  cp fpga/diamond/impl1/aw2_impl1_empty.config {baseline_path}"
        )

    print(f"Loading baseline: {baseline_path}")
    base_tiles = parse_config(baseline_path.read_text())
    print(f"  Baseline has {len(base_tiles)} tiles")

    # Discover result configs
    config_files = sorted(results_dir.glob("*/*.config"))
    if not config_files:
        sys.exit(f"No .config files found under {results_dir}")
    print(f"Found {len(config_files)} result configs\n")

    # Per-target analysis
    family_data:   dict[str, dict[str, dict]] = defaultdict(dict)  # family → {target: diff}
    target_summary: list[tuple[str, int, int]] = []   # (name, n_tiles, n_bits)

    for cfg_path in config_files:
        target_name = cfg_path.parent.name
        try:
            fuzz_tiles = parse_config(cfg_path.read_text())
        except Exception as e:
            print(f"  ERROR  {target_name}: {e}")
            continue

        diff = diff_configs(base_tiles, fuzz_tiles)
        n_tiles = len(diff)
        n_bits  = sum(len(v) for v in diff.values())

        family = get_family(target_name)
        family_data[family][target_name] = diff
        target_summary.append((target_name, n_tiles, n_bits))

        print(f"  {target_name:<45s}  {n_tiles:3d} tiles  {n_bits:5d} bits changed")

    # Write per-family bit reports
    for family, targets in sorted(family_data.items()):
        out_path = results_dir / f"{family}_bits.txt"
        lines = [f"# {family} — changed bits vs baseline", ""]

        for target_name, diff in sorted(targets.items()):
            lines.append(f"## {target_name}")
            if not diff:
                lines.append("  (no bits changed — synthesis optimised away?)")
            for tile, bits in sorted(diff.items()):
                lines.append(f"  tile {tile}:")
                for frame, bit in bits:
                    lines.append(f"    F{frame:03d}B{bit:03d}")
            lines.append("")

        # Bank consistency cross-check for this family
        cc_lines = cross_check_banks(targets)
        if cc_lines:
            lines.append("## Bank consistency cross-check")
            lines.extend(cc_lines)
            lines.append("")

        out_path.write_text("\n".join(lines) + "\n")
        print(f"  Wrote {out_path.name}  ({len(targets)} targets)")

    # Master summary
    summary_path = results_dir / "parse_summary.txt"
    s_lines = [
        "=== parse_results.py summary ===",
        f"Baseline:  {baseline_path}",
        f"Results:   {results_dir}",
        f"Targets:   {len(target_summary)}",
        "",
        f"{'Target':<45s}  {'Tiles':>5s}  {'Bits':>6s}  Family",
        "-" * 80,
    ]
    for name, n_tiles, n_bits in sorted(target_summary):
        family = get_family(name)
        s_lines.append(f"{name:<45s}  {n_tiles:5d}  {n_bits:6d}  {family}")

    s_lines += [
        "",
        "Families covered:",
    ]
    for family in sorted(family_data):
        n = len(family_data[family])
        s_lines.append(f"  {family:<30s}  {n} targets")

    # Flag suspicious targets (0 bits changed — synthesis trimmed the primitive)
    zero_bit = [n for n, t, b in target_summary if b == 0]
    if zero_bit:
        s_lines += ["", "WARNING — zero bits changed (synthesis may have optimised away):"]
        for n in zero_bit:
            s_lines.append(f"  {n}")

    summary_path.write_text("\n".join(s_lines) + "\n")
    print(f"\nSummary written to {summary_path}")
    print(f"Per-family reports written to {results_dir}/<FAMILY>_bits.txt")


if __name__ == "__main__":
    main()
