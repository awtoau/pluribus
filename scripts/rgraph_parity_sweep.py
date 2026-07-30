#!/usr/bin/env python3.15t
"""Parity-check the native routing graph on EVERY device, one at a time (#97).

WHY A SWEEP
-----------
The routing graph is a pure function of the device, so parity is only ever proven
for the devices actually checked.  After the ECP5 dispatcher fix, parity held
exhaustively on LFE5U-12F and LCMXO2-1200 -- two devices out of sixteen.  Retiring
pytrellis rests on the rest of them, and nothing about a 12F result generalises to
an 85F: different grid, different globalise tables, different tile mix.

WHY IT DELETES AS IT GOES
-------------------------
A golden dump is exhaustive and therefore enormous -- 435 MB for the SMALLEST ECP5
part, and the 85F devices are several times that.  Sixteen kept at once would be a
disk problem for no benefit: the golden is a regenerable intermediate whose only
purpose is to be compared once.  So each device is dumped, checked, and its golden
removed before moving on, with a free-space floor as a backstop.  `--keep` retains
them for debugging a specific failure.

Small devices first, deliberately.  A systematic port bug shows up on a 256-cell
MachXO2 in seconds; discovering it after an hour of 85F dumping wastes the hour.

SIXTEEN DEVICES IS NOT SIXTEEN SAMPLES -- read the coverage claim carefully.
The ECP5 parts share dies.  Identical `frames` x `bits_per_frame` in devices.json,
identical tile counts, identical globalise counts:

    7562 x 592   LFE5U-12F, LFE5U-25F, LFE5UM-25F, LFE5UM5G-25F
    9470 x 846   LFE5U-45F, LFE5UM-45F, LFE5UM5G-45F
    13294 x 1136 LFE5U-85F, LFE5UM-85F, LFE5UM5G-85F

Only the IDCODE's top nibble separates them (2=12F, 4=U, 0=UM, 8=UM5G), which is
how the configuration engine tells parts apart on shared silicon.  The UM/UM5G
variants add a few hundred globalise entries for SERDES/PCS wiring and nothing
else.  So the ten ECP5 devices are THREE independent fabric geometries, and 12F in
particular is not a cheap small sample -- it is the 25F sample.  The six MachXO2
parts do have genuinely distinct tile counts (88/171/322/459/792/1260).

Effective independent coverage is therefore about NINE configurations, not sixteen.
The sweep still runs all sixteen -- per-device IDCODE and variant handling is worth
exercising, and it is cheap once the die is dumped -- but a summary saying "16/16
devices" overstates the fabric variety behind it.

    scripts/rgraph_parity_sweep.py [--devices A,B] [--family ECP5|MachXO2]
                                   [--keep] [--min-free-gb 40]

Needs the pytrellis .so to GENERATE goldens (the checker itself needs no .so).
Logs to ./tmp/logs/rgraph_parity_sweep.log; JSON to tmp/rgraph_parity_sweep.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toolchain  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"

# Ascending size, so a systematic failure surfaces cheaply.  Sizes are the reason
# for the order, not alphabety: LCMXO2-256 is ~1/50th of an LFE5U-85F.
MACHXO2 = ["LCMXO2-256", "LCMXO2-640", "LCMXO2-1200", "LCMXO2-2000",
           "LCMXO2-4000", "LCMXO2-7000"]
ECP5 = ["LFE5U-12F", "LFE5U-25F", "LFE5UM-25F", "LFE5UM5G-25F",
        "LFE5U-45F", "LFE5UM-45F", "LFE5UM5G-45F",
        "LFE5U-85F", "LFE5UM-85F", "LFE5UM5G-85F"]


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("rgraph_parity_sweep")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "rgraph_parity_sweep.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def resolve_trellis(log):
    """The .so build dir and the database that MUST match it.

    Both come from one prjtrellis source checkout on purpose.  Comparing a native
    port against a golden dumped by one Trellis build, using tile data from a
    different build, would attribute the version difference to our port.  $TRELLIS_
    BUILD / $TRELLIS_DBROOT still win if set (#90).
    """
    build = os.environ.get("TRELLIS_BUILD")
    dbroot = os.environ.get("TRELLIS_DBROOT")
    if build and dbroot:
        return build, dbroot
    root = toolchain.sibling_repo("prjtrellis", "TRELLIS_ROOT",
                                  "prjtrellis source build", required=False)
    if not root:
        toolchain.die("cannot find a prjtrellis checkout for the pytrellis .so; "
                      "set $TRELLIS_BUILD and $TRELLIS_DBROOT")
    # A free-threaded build is required: a stock one re-enables the GIL or
    # segfaults under 3.15t, and native_rgraph_golden.py asserts on that.
    for cand in ("build_315", "build_ft", "build"):
        p = os.path.join(root, "libtrellis", cand)
        if os.path.isfile(os.path.join(p, "pytrellis.so")):
            log.info("pytrellis .so: %s", p)
            return build or p, dbroot or os.path.join(root, "database")
    toolchain.die(f"no pytrellis.so under {root}/libtrellis/build*")


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9


def sweep_one(device, build, dbroot, keep, log):
    """Dump a golden, parity-check it, then drop it.  Returns a result dict."""
    golden = REPO / "tmp" / f"rgraph_golden_{device}.json"
    env = dict(os.environ, TRELLIS_BUILD=str(build), TRELLIS_DBROOT=str(dbroot))
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, str(REPO / "scripts/native_rgraph_golden.py"),
                        device, str(golden)], capture_output=True, text=True, env=env)
    dump_s = time.monotonic() - t0
    if r.returncode != 0:
        log.error("  %s: golden dump FAILED rc=%d: %s", device, r.returncode,
                  (r.stderr or r.stdout).strip()[-300:])
        return {"device": device, "stage": "golden", "ok": False,
                "note": (r.stderr or r.stdout).strip()[-300:]}
    size_gb = golden.stat().st_size / 1e9

    t1 = time.monotonic()
    # The checker deliberately gets no TRELLIS_BUILD: it must pass without the .so,
    # which is the property being demonstrated.
    p = subprocess.run([sys.executable, str(REPO / "scripts/native_rgraph_parity.py"),
                        str(golden)], capture_output=True, text=True,
                       env=dict(os.environ, TRELLIS_DBROOT=str(dbroot)))
    check_s = time.monotonic() - t1
    ok = p.returncode == 0
    out = (p.stdout or "").strip().splitlines()
    for line in out:
        log.info("    %s", line)
    if not ok:
        log.error("  %s: PARITY FAILED rc=%d", device, p.returncode)
        if p.stderr.strip():
            log.error("    %s", p.stderr.strip()[-400:])
    if not keep:
        golden.unlink(missing_ok=True)
    log.info("  %s: %s  (golden %.2f GB in %.0fs, check %.0fs)", device,
             "PASS" if ok else "FAIL", size_gb, dump_s, check_s)
    return {"device": device, "stage": "parity", "ok": ok,
            "golden_gb": round(size_gb, 3), "dump_s": round(dump_s),
            "check_s": round(check_s),
            "note": "" if ok else (p.stdout or p.stderr).strip()[-400:]}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--devices", default="", help="comma-separated override")
    ap.add_argument("--family", default="", choices=("", "ECP5", "MachXO2"))
    ap.add_argument("--keep", action="store_true",
                    help="keep goldens (debugging; they are large)")
    ap.add_argument("--min-free-gb", type=float, default=40.0,
                    help="stop before a dump if free space is below this")
    ap.add_argument("--json", default=str(REPO / "tmp/rgraph_parity_sweep.json"))
    args = ap.parse_args()
    log = setup_logging()

    if args.devices:
        devices = [d.strip() for d in args.devices.split(",") if d.strip()]
    elif args.family == "ECP5":
        devices = ECP5
    elif args.family == "MachXO2":
        devices = MACHXO2
    else:
        devices = MACHXO2 + ECP5

    build, dbroot = resolve_trellis(log)
    log.info("database: %s", dbroot)
    log.info("sweeping %d device(s), smallest first: %s", len(devices),
             ", ".join(devices))

    results = []
    for device in devices:
        if free_gb(REPO) < args.min_free_gb:
            log.error("stopping: only %.1f GB free, below the %.1f GB floor. "
                      "%d device(s) not checked: %s", free_gb(REPO),
                      args.min_free_gb, len(devices) - len(results),
                      ", ".join(devices[len(results):]))
            break
        log.info("---- %s ----", device)
        results.append(sweep_one(device, build, dbroot, args.keep, log))

    passed = [r["device"] for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    skipped = [d for d in devices if d not in [r["device"] for r in results]]
    with open(args.json, "w") as fh:
        json.dump({"passed": passed, "failed": failed, "skipped": skipped,
                   "results": results}, fh, indent=2, sort_keys=True)
    log.info("==== %d/%d PASS ====", len(passed), len(results))
    for r in failed:
        log.error("  FAIL %s (%s)", r["device"], r["stage"])
    if skipped:
        log.info("  not checked: %s", ", ".join(skipped))
    log.info("results -> %s", args.json)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
