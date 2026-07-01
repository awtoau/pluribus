#!/usr/bin/env python3
"""run_prjtrellis_check.py — verify prjtrellis bits.db against Diamond 3.14.

For every fuzzer directory that has a check.py, run it. check.py builds a full
parameter sweep and verifies every resulting bitstream against bits.db. Every
discrepancy is reported — nothing is swallowed or hidden. Exit code is nonzero
if ANY check fails.

Usage:
    python3 run_prjtrellis_check.py             # all fuzzers with check.py
    python3 run_prjtrellis_check.py "103-*"     # pattern filter

Output:
    tmp/prjtrellis_check/<fuzzer_name>.log  — per-fuzzer stdout+stderr
    tmp/prjtrellis_check/summary.txt        — one line per fuzzer + totals
    tmp/prjtrellis_check/all_mismatches.txt — every mismatch line
"""
from __future__ import annotations
import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

_ROOT     = Path(__file__).parent
_PRJT     = Path("/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis")
_FUZZ_DIR = _PRJT / "fuzzers/machxo2"
_LOG_DIR  = _ROOT / "tmp/prjtrellis_check"

_MISMATCH_RE = re.compile(
    r"^(BIT_MISMATCH|MISSING_IN_DB|MISSING_VALUE|MISSING_BIT|MISMATCH:|!!! DATABASE)"
)

_ENV_EXTRA = {
    "DIAMONDDIR":       "/home/dan/lscc/diamond/3.14",
    "DIAMONDVER":       "3.14",
    "LM_LICENSE_FILE":  "/home/dan/lscc/diamond/3.14/license/license.dat",
    "PYTHONPATH":       ":".join([
        str(_PRJT / "libtrellis/build"),
        str(_PRJT / "util/fuzz"),
        str(_PRJT / "util/common"),
        str(_PRJT / "util/common/nets"),
        str(_PRJT / "util"),
    ]),
    "LD_LIBRARY_PATH":  str(_PRJT / "libtrellis/build"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", nargs="?", default="*", help="Glob filter on fuzzer dir names")
    args = ap.parse_args()

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    summary_file    = _LOG_DIR / "summary.txt"
    mismatches_file = _LOG_DIR / "all_mismatches.txt"
    summary_file.write_text("")
    mismatches_file.write_text("")

    env = {**os.environ, **_ENV_EXTRA}

    fuzz_dirs = sorted(_FUZZ_DIR.iterdir())
    passed, mismatches, build_fails, skipped = [], [], [], []

    for fuzzer_dir in fuzz_dirs:
        if not fuzzer_dir.is_dir():
            continue
        name = fuzzer_dir.name
        if not fnmatch.fnmatch(name, args.pattern):
            skipped.append(name)
            continue
        if not (fuzzer_dir / "check.py").exists():
            skipped.append(name)
            continue

        log = _LOG_DIR / f"{name}.log"
        print(f"  [check] {name} ...", flush=True)

        with open(log, "w") as lf:
            rc = subprocess.run(
                [sys.executable, "check.py"],
                cwd=str(fuzzer_dir),
                env=env,
                stdout=lf,
                stderr=lf,
            ).returncode

        log_text  = log.read_text()
        log_lines = log_text.splitlines()
        mismatch_lines = [l for l in log_lines if _MISMATCH_RE.match(l)]

        if rc == 0 and not mismatch_lines:
            passed.append(name)
            print(f"  PASS  {name}", flush=True)
            with open(summary_file, "a") as sf:
                sf.write(f"PASS  {name}\n")

        elif mismatch_lines:
            mismatches.append(name)
            with open(mismatches_file, "a") as mf:
                for l in mismatch_lines:
                    mf.write(f"  {name}: {l}\n")
            print(f"\n{'!'*74}", flush=True)
            print(f"  DATABASE MISMATCH: {name}  (rc={rc})", flush=True)
            for l in mismatch_lines:
                print(f"    {l}", flush=True)
            print(f"  Full log: {log}", flush=True)
            print(f"{'!'*74}\n", flush=True)
            label = "WARNING_MISMATCH" if rc == 0 else "MISMATCH"
            with open(summary_file, "a") as sf:
                sf.write(f"{label}  {name}\n")

        else:
            build_fails.append(name)
            print(f"  BUILD_FAIL  {name}  (rc={rc} — see {log})", flush=True)
            for l in log_lines[-8:]:
                print(f"    {l}", flush=True)
            with open(summary_file, "a") as sf:
                sf.write(f"BUILD_FAIL  {name}\n")

    summary = (
        f"\n=== Check run summary ===\n"
        f"  Passed:      {len(passed)}\n"
        f"  MISMATCHES:  {len(mismatches)}\n"
        f"  Build fails: {len(build_fails)}\n"
        f"  Skipped:     {len(skipped)} (no check.py or filtered)\n"
    )
    with open(summary_file, "a") as sf:
        sf.write(summary)
    print(summary, flush=True)

    overall_fail = False

    if mismatches:
        overall_fail = True
        print(f"{'!'*74}", flush=True)
        print(f"  DATABASE MISMATCHES — Diamond 3.14 disagrees with prjtrellis database:", flush=True)
        for f in mismatches:
            print(f"    {f}", flush=True)
        print(f"  Combined mismatch file: {mismatches_file}", flush=True)
        print(f"{'!'*74}", flush=True)

    if build_fails:
        overall_fail = True
        print(f"{'!'*74}", flush=True)
        print(f"  BUILD FAILURES (Diamond/pytrellis error, not a bit mismatch):", flush=True)
        for f in build_fails:
            print(f"    {f}", flush=True)
        print(f"  Logs: {_LOG_DIR}/", flush=True)
        print(f"{'!'*74}", flush=True)

    if not overall_fail:
        print(f"  ALL CHECKS PASSED — Diamond 3.14 matches prjtrellis database.", flush=True)
        print(f"  Summary: {summary_file}", flush=True)

    sys.exit(1 if overall_fail else 0)


if __name__ == "__main__":
    main()
