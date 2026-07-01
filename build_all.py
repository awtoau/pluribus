#!/usr/bin/env python3
"""build_all.py — run generic MachXO2 toolchain pipelines in dependency order.

Pipelines (run in this order — each feeds the next):
  1. prjtrellis fuzz  — Diamond 3.14 fuzzer suite → generates bits.db (opt-in --prjt-fuzz)
  2. prjtrellis check — verify bits.db against Diamond (opt-in --prjt-check)
  3. Diamond fuzz     — synthesise IOLOGIC test designs → PAR + bitstreams (opt-in --diamond)
  4. MachXO2 fuzz    — routing fuzzer → fuzz_runs/fuzz_wires in postgres (opt-in --fuzz)

All pipelines are opt-in. Run from the pluribus repo root.

Note: the Pluribus RE pipeline (loading a specific bitstream and running the
full analysis) lives in each target project — e.g. awto-2000/fpga/scripts/run_pluribus.py.

Usage:
    python3 build_all.py --prjt-fuzz       # prjtrellis fuzzer → bits.db
    python3 build_all.py --prjt-check      # verify bits.db against Diamond
    python3 build_all.py --diamond         # Diamond IOLOGIC fuzz builds
    python3 build_all.py --fuzz            # MachXO2 routing fuzzer
    python3 build_all.py --all             # all 4 pipelines

Logs: tmp/build_all.log, tmp/fuzz_full.log,
      tmp/prjtrellis_run/, tmp/prjtrellis_check/
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent


def run(label: str, cmd: list, log_path: Path | None = None) -> bool:
    print(f"\n{'='*60}", flush=True)
    print(f"PIPELINE {label}", flush=True)
    t0 = time.time()
    kwargs: dict = dict(args=[str(c) for c in cmd])
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Log: {log_path}", flush=True)
        lf = open(log_path, "w")
        kwargs["stdout"] = lf
        kwargs["stderr"] = lf
    proc = subprocess.run(**kwargs)
    elapsed = time.time() - t0
    if log_path:
        lf.close()
    ok = proc.returncode == 0
    print(f"{'OK' if ok else f'FAILED (rc={proc.returncode})'} ({elapsed:.1f}s)", flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prjt-fuzz",  action="store_true", help="Pipeline 1: prjtrellis fuzzer → bits.db")
    ap.add_argument("--prjt-check", action="store_true", help="Pipeline 2: verify bits.db against Diamond")
    ap.add_argument("--diamond",    action="store_true", help="Pipeline 3: Diamond IOLOGIC fuzz builds")
    ap.add_argument("--fuzz",       action="store_true", help="Pipeline 4: MachXO2 routing fuzzer")
    ap.add_argument("--all",        action="store_true", help="Run all 4 pipelines")
    args = ap.parse_args()

    if args.all:
        args.prjt_fuzz = args.prjt_check = args.diamond = args.fuzz = True

    if not any([args.prjt_fuzz, args.prjt_check, args.diamond, args.fuzz]):
        ap.print_help()
        sys.exit(0)

    failed = []

    if args.prjt_fuzz:
        if not run("1 — prjtrellis fuzzer",
                   [sys.executable, str(_ROOT / "run_prjtrellis_fuzz.py")]):
            failed.append("1-prjt-fuzz")

    if args.prjt_check:
        if not run("2 — prjtrellis check",
                   [sys.executable, str(_ROOT / "run_prjtrellis_check.py")]):
            failed.append("2-prjt-check")

    if args.diamond:
        if not run("3 — Diamond IOLOGIC fuzz",
                   [sys.executable, str(_ROOT / "diamond-fuzz/scripts/run_all_fuzz.py")],
                   _ROOT / "tmp/diamond_fuzz.log"):
            failed.append("3-diamond")

    if args.fuzz:
        if not run("4 — MachXO2 routing fuzzer",
                   [sys.executable, str(_ROOT / "run_machxo2_fuzz.py")],
                   _ROOT / "tmp/fuzz_full.log"):
            failed.append("4-fuzz")

    print(f"\n{'='*60}", flush=True)
    if failed:
        print(f"FAILED pipelines: {', '.join(failed)}", flush=True)
        sys.exit(1)
    else:
        ran = []
        if args.prjt_fuzz:  ran.append("1-prjt-fuzz")
        if args.prjt_check: ran.append("2-prjt-check")
        if args.diamond:    ran.append("3-diamond")
        if args.fuzz:       ran.append("4-fuzz")
        print(f"All done: {', '.join(ran)}", flush=True)


if __name__ == "__main__":
    main()
