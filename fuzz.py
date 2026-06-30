#!/usr/bin/env python3
"""Pluribus fuzzer — load multiple bitstreams and compare structural signatures.

For each test bitstream in tests/<name>/*.cfg or *.bin.config:
  1. Drop + rebuild the DB for that label
  2. Assert known structural properties (from a manifest)
  3. Write diff-friendly output TSV
  4. Compare against other labels — spot routing/synthesis patterns

Usage
-----
  TRELLIS_DBROOT=... PYTHONPATH=... python3 fpga/pluribus/fuzz.py \
      --device LCMXO2-1200 \
      [--test blank] [--test one_ff] [--test shift_reg_8]  # or all if omitted
      [--out-dir fpga/pluribus/tests/out]

Manifest format (tests/<name>/manifest.json):
  {
    "config":   "top.cfg",          // bitstream config file
    "pins_tsv": "pins.tsv",         // optional pin annotation (or use minimal defaults)
    "expect": {
      "ffs":   1,                   // exact count or null to skip check
      "luts":  0,
      "shift_regs":  null,          // pattern count
      "efb_ports":   null
    }
  }
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE   = Path(__file__).parent
_TESTS  = _HERE / "tests"
_BUILD  = _HERE / "build.py"

import sys as _sys
_sys.path.insert(0, str(_HERE))
from db import engine, die
import schema
from sqlalchemy import select, func


def run_test(name, test_dir, out_dir, device):
    """Run one test: load + assert + export."""
    manifest_path = test_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"  SKIP {name} — no manifest.json")
        return None

    with open(manifest_path) as fh:
        m = json.load(fh)

    config = test_dir / m.get("config", "top.cfg")
    if not config.exists():
        print(f"  SKIP {name} — config {config} not found (bitstream not yet synthesised)")
        return None

    # Use the test-specific pins TSV if it exists, otherwise generate a minimal
    # valid one.  load.py requires at least one non-nc/cfg pin row to pass its
    # fail-fast check — write a single dummy 'nc' pin which is skipped during
    # fabric resolution but satisfies the non-empty row requirement.
    pins_tsv = test_dir / m.get("pins_tsv", "pins.tsv")
    if not pins_tsv.exists():
        pins_tsv = out_dir / f"{name}-pins-auto.tsv"
        pins_tsv.parent.mkdir(parents=True, exist_ok=True)
        with open(pins_tsv, "w") as fh:
            fh.write(f"# device: {device}\n")
            fh.write(f"# package: TQFP100\n")
            fh.write(f"# crystal: unknown\n")
            fh.write(f"# jtag: unknown\n")
            # One dummy bidir pin so parse_pins_tsv returns a non-empty list;
            # row/col/pio are 0/0/A (valid placeholder — may not resolve, which is OK)
            fh.write("1\t0\t0\tA\tbidir\tTEST_PIN1\t(auto-generated)\t1\n")

    label = f"TEST_{name.upper()}"
    test_out = out_dir / name
    test_out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(f"\n── {name} ──")
    r = subprocess.run([
        sys.executable, str(_BUILD), "build",
        "--label",   label,
        "--config",  str(config),
        "--pins",    str(pins_tsv),
        "--device",  device,
        "--out-dir", str(test_out),
    ])
    if r.returncode != 0:
        print(f"  FAIL {name} — build failed", file=sys.stderr)
        return {"name": name, "status": "FAIL", "error": "build failed"}

    # Verify expectations from manifest
    with engine().connect() as conn:
        row = conn.execute(
            select(schema.bitstreams.c.id)
            .where(schema.bitstreams.c.label == label)
        ).fetchone()
        if not row:
            die(f"Bitstream {label!r} not found after successful build")
        bs_id = row[0]

        results = {"name": name, "status": "OK", "checks": []}
        expect  = m.get("expect", {})

        def check(what, table, expected):
            got = conn.execute(
                select(func.count()).select_from(table)
                .where(table.c.bitstream == bs_id)
            ).scalar()
            ok  = (expected is None or got == expected)
            status = "OK" if ok else "FAIL"
            results["checks"].append({"what": what, "got": got, "expected": expected, "status": status})
            if not ok:
                results["status"] = "FAIL"
            print(f"  {status:4s}  {what}: got={got}" + (f" expected={expected}" if expected is not None else ""))

        check("ffs",        schema.ffs,          expect.get("ffs"))
        check("luts",       schema.luts,         expect.get("luts"))
        check("nets",       schema.nets,         expect.get("nets"))
        check("efb_ports",  schema.efb_ports,    expect.get("efb_ports"))
        check("reach_pairs",schema.reachability, expect.get("reach_pairs"))

    results["elapsed"] = time.time() - t0
    print(f"  {results['status']}  ({results['elapsed']:.1f}s)")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device",  default="LCMXO2-1200")
    ap.add_argument("--test",    action="append", dest="tests",
                    help="test name (default: all that have manifest.json)")
    ap.add_argument("--out-dir", default="fpga/pluribus/tests/out")
    args = ap.parse_args()

    out_dir   = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.tests:
        test_names = args.tests
    else:
        test_names = [d.name for d in _TESTS.iterdir()
                      if d.is_dir() and (d / "manifest.json").exists()]

    print(f"Running {len(test_names)} tests: {test_names}")

    all_results = []
    for name in test_names:
        test_dir = _TESTS / name
        if not test_dir.is_dir():
            print(f"  SKIP {name} — directory not found")
            continue
        r = run_test(name, test_dir, out_dir, args.device)
        if r:
            all_results.append(r)

    # Summary
    print("\n══ Fuzz summary ══")
    ok   = sum(1 for r in all_results if r["status"] == "OK")
    fail = sum(1 for r in all_results if r["status"] == "FAIL")
    skip = len(test_names) - len(all_results)
    print(f"  OK={ok}  FAIL={fail}  SKIP={skip}")

    # Write JSON report
    report = out_dir / "fuzz_report.json"
    with open(report, "w") as fh:
        json.dump(all_results, fh, indent=2)
    print(f"  Report: {report}")

    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
