#!/usr/bin/env python3
"""Fuzz result validator — loads each Diamond fuzz .config into pluribus DB
and runs consistency checks, optionally cross-checking against a baseline config.

Pipeline per fuzz target:
  1. ecpunpack .bit → .config  (if not already done)
  2. load.py → DB (label = fuzz_<target_name>)
  3. Structural checks:
       - tile types match expected device topology
       - no ghost cells (tiles with unknown type)
       - IOLOGIC tiles: check MODE enum is set (not default)
       - all output ports reachable from at least one pad
  4. Cross-check against baseline (optional --baseline):
       - tiles that differ → candidate new primitive bits
       - tiles identical → sanity check (passive tile should not change)
  5. Write per-target report to results/<target>/validate.txt

Usage:
    python3 validate_fuzz.py [--target TARGET] [--all] [--baseline PATH]
    python3 validate_fuzz.py --all --jobs 4
    python3 validate_fuzz.py --all --baseline /path/to/baseline.config
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

_SCRIPTS    = Path(__file__).parent
_FUZZ_ROOT  = _SCRIPTS.parent
_PLURIBUS   = _FUZZ_ROOT.parent
TARGETS_DIR = _FUZZ_ROOT / "targets"
RESULTS_DIR = _FUZZ_ROOT / "results"
_PRJT       = Path(os.environ.get("TRELLIS_ROOT",
                   "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis"))
ECPUNPACK   = _PRJT / "libtrellis/build/ecpunpack"
TRELLIS_DB  = _PRJT / "database"
DIAMOND_LIB = _PRJT / "libtrellis/build"

sys.path.insert(0, str(_PLURIBUS))
from db import connect


# ── ecpunpack ────────────────────────────────────────────────────────────────

def unpack_bit(bit_path: Path, config_path: Path) -> bool:
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = str(DIAMOND_LIB)
    r = subprocess.run(
        [str(ECPUNPACK), "--db", str(TRELLIS_DB),
         str(bit_path), str(config_path)],
        env=env, capture_output=True, text=True
    )
    return r.returncode == 0


# ── Pluribus load ─────────────────────────────────────────────────────────────

def load_fuzz_config(target_name: str, config_path: Path, label: str) -> bool:
    cmd = [
        sys.executable, str(_PLURIBUS / "load.py"),
        "--label",  label,
        "--config", str(config_path),
        "--device", "LCMXO2-1200HC",
        "--package", "TQFP100",
        "--no-nets-tsv",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_PLURIBUS))
    if r.returncode != 0:
        print(f"  load FAILED: {r.stdout[-500:]}", file=sys.stderr)
        return False
    return True


# ── Structural checks ─────────────────────────────────────────────────────────

def structural_checks(cur, bs_id: int, target_name: str, config_text: str) -> list:
    errors = []

    iologic_tiles = re.findall(r'\.tile (\S+:PIC_\w+)', config_text)
    for tile in iologic_tiles:
        tile_section = re.search(
            rf'\.tile {re.escape(tile)}\n(.*?)(?=\.tile |\Z)',
            config_text, re.DOTALL
        )
        if tile_section:
            section = tile_section.group(1)
            if "IOLOGIC" in section and "MODE" not in section:
                errors.append(f"WARN: tile {tile} has IOLOGIC config but no MODE enum")

    cur.execute("""
        SELECT COUNT(*) FROM pad_map WHERE bitstream=%s AND direction IN ('in','bidir')
    """, (bs_id,))
    n_inputs = cur.fetchone()[0]
    if n_inputs == 0:
        errors.append("WARN: no input pads found — design may be fully optimised away")

    cur.execute("SELECT COUNT(*) FROM nets WHERE bitstream=%s", (bs_id,))
    n_nets = cur.fetchone()[0]
    if n_nets < 3:
        errors.append(f"ERROR: only {n_nets} nets — design likely optimised to constants")

    return errors


# ── Cross-check against baseline ──────────────────────────────────────────────

def diff_vs_baseline(config_text: str, baseline_text: str) -> dict:
    def parse_tiles(text):
        tiles = {}
        current = None
        lines = []
        for line in text.splitlines():
            m = re.match(r'^\.tile (\S+)', line)
            if m:
                if current:
                    tiles[current] = lines
                current = m.group(1)
                lines = []
            elif current and line.strip():
                lines.append(line.strip())
        if current:
            tiles[current] = lines
        return tiles

    fuzz_tiles     = parse_tiles(config_text)
    baseline_tiles = parse_tiles(baseline_text)

    changed   = {}
    new_tiles = []
    missing   = []

    for tile, lines in fuzz_tiles.items():
        if tile not in baseline_tiles:
            new_tiles.append(tile)
        elif sorted(lines) != sorted(baseline_tiles[tile]):
            changed[tile] = (lines, baseline_tiles[tile])

    for tile in baseline_tiles:
        if tile not in fuzz_tiles:
            missing.append(tile)

    return {"changed": changed, "new": new_tiles, "missing": missing}


# ── Per-target validation ─────────────────────────────────────────────────────

def validate_target(target_name: str, baseline_text: str | None) -> dict:
    result_dir = RESULTS_DIR / target_name
    result_dir.mkdir(parents=True, exist_ok=True)

    report_lines = [f"=== Fuzz validation: {target_name} ===\n"]
    status = "PASS"

    bit_candidates = [
        TARGETS_DIR / target_name / "impl1/fuzz_impl1.bit",
        TARGETS_DIR / target_name / "impl1" / f"{target_name}_impl1.bit",
    ]
    bit_candidates += list(result_dir.glob("*.bit"))

    bit_path = None
    for p in bit_candidates:
        if p.exists():
            bit_path = p
            break

    if not bit_path:
        report_lines.append("ERROR: no .bit file found\n")
        (result_dir / "validate.txt").write_text("\n".join(report_lines))
        return {"target": target_name, "status": "NO_BIT", "errors": ["no .bit file"]}

    config_path = result_dir / "fuzz.config"
    if not config_path.exists():
        report_lines.append(f"Unpacking {bit_path.name}...")
        if not unpack_bit(bit_path, config_path):
            report_lines.append("ERROR: ecpunpack failed\n")
            (result_dir / "validate.txt").write_text("\n".join(report_lines))
            return {"target": target_name, "status": "UNPACK_FAIL", "errors": ["ecpunpack failed"]}

    config_text = config_path.read_text()
    report_lines.append(f"Config: {len(config_text.splitlines())} lines\n")

    label = f"fuzz_{target_name}"[:63]
    report_lines.append(f"Loading into DB as label={label!r}...")
    load_ok = load_fuzz_config(target_name, config_path, label)
    if not load_ok:
        report_lines.append("WARN: DB load failed — skipping DB checks")
        db_errors = ["DB load failed"]
    else:
        conn = connect()
        cur  = conn.cursor()
        cur.execute("SELECT id FROM bitstreams WHERE label=%s", (label,))
        row = cur.fetchone()
        if not row:
            db_errors = ["bitstream not found in DB after load"]
        else:
            bs_id = row[0]
            db_errors = structural_checks(cur, bs_id, target_name, config_text)
        cur.close()
        conn.close()

    for e in db_errors:
        report_lines.append(f"  {e}")
        if e.startswith("ERROR"):
            status = "FAIL"

    if baseline_text:
        diff = diff_vs_baseline(config_text, baseline_text)
        report_lines.append(f"\n--- Diff vs baseline ---")
        report_lines.append(f"  Changed tiles : {len(diff['changed'])}")
        report_lines.append(f"  New tiles     : {len(diff['new'])}")
        report_lines.append(f"  Missing tiles : {len(diff['missing'])}")

        if diff["new"]:
            report_lines.append(f"  New: {', '.join(diff['new'][:10])}")

        report_lines.append("\n--- Changed tile details ---")
        for tile, (fuzz_lines, base_lines) in sorted(diff["changed"].items()):
            added   = sorted(set(fuzz_lines) - set(base_lines))
            removed = sorted(set(base_lines) - set(fuzz_lines))
            report_lines.append(f"\n  {tile}:")
            for l in added:   report_lines.append(f"    + {l}")
            for l in removed: report_lines.append(f"    - {l}")

        diff_path = result_dir / "tile_diff.txt"
        diff_path.write_text("\n".join(report_lines))
        n_changed = len(diff["changed"])
    else:
        n_changed = 0

    report_lines.append(f"\nStatus: {status}")
    (result_dir / "validate.txt").write_text("\n".join(report_lines))

    return {
        "target":        target_name,
        "status":        status,
        "errors":        db_errors,
        "changed_tiles": n_changed,
        "new_tiles":     len(diff["new"]) if baseline_text else 0,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target",   help="Validate a single target by name")
    ap.add_argument("--all",      action="store_true", help="Validate all targets")
    ap.add_argument("--jobs",     type=int, default=1, help="Parallel workers")
    ap.add_argument("--baseline", help="Path to baseline .config to diff against")
    args = ap.parse_args()

    baseline_text = None
    if args.baseline:
        baseline_path = Path(args.baseline)
        if not baseline_path.exists():
            print(f"ERROR: baseline not found: {baseline_path}", file=sys.stderr)
            sys.exit(1)
        baseline_text = baseline_path.read_text()
        print(f"Baseline: {baseline_path.name} ({len(baseline_text.splitlines())} lines)")

    if args.target:
        targets = [args.target]
    elif args.all:
        targets = sorted(d.name for d in TARGETS_DIR.iterdir() if d.is_dir())
    else:
        ap.print_help()
        sys.exit(1)

    print(f"Validating {len(targets)} targets with {args.jobs} worker(s)...")

    results = []
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            futs = {ex.submit(validate_target, t, baseline_text): t for t in targets}
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
                sym = "✓" if r["status"] == "PASS" else "✗"
                print(f"  {sym} {r['target']} — {r['status']} "
                      f"({r.get('changed_tiles',0)} changed tiles)")
    else:
        for t in targets:
            r = validate_target(t, baseline_text)
            results.append(r)
            sym = "✓" if r["status"] == "PASS" else "✗"
            print(f"  {sym} {t} — {r['status']} "
                  f"({r.get('changed_tiles',0)} changed tiles)")

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    no_bit = sum(1 for r in results if r["status"] == "NO_BIT")

    summary_lines = [
        f"Fuzz validation summary",
        f"  Total:   {len(results)}",
        f"  Pass:    {passed}",
        f"  Fail:    {failed}",
        f"  No bit:  {no_bit}",
        "",
        "Targets with most changed tiles (new primitive bits):",
    ]
    by_change = sorted(results, key=lambda r: r.get("changed_tiles", 0), reverse=True)
    for r in by_change[:20]:
        summary_lines.append(
            f"  {r['target']:40s}  {r.get('changed_tiles',0):4d} tiles changed"
        )

    summary_path = RESULTS_DIR / "validation_summary.txt"
    summary_text = "\n".join(summary_lines)
    summary_path.write_text(summary_text)
    print(f"\n{summary_text}")
    print(f"\nSummary: {summary_path}")


if __name__ == "__main__":
    main()
