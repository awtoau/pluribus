#!/usr/bin/env python3.15t
"""Round-trip the ECP5 lifter across every available build, in parallel.

One design passing proves the decode works on one design.  This runs the same
verification over every ECP5 build directory it can find, because the failure
modes that matter (a tile type that only appears in bigger designs, a routing
case that only a DSP/BRAM design exercises) do not show up in the small one.

Parallelism is the point of the free-threaded interpreter here: the routing
graph build dominates (~11s) and each worker needs its own, so the designs run
concurrently on real threads rather than serially.  There is no shared mutable
state between workers — each owns its lifter — which is the pattern the rest
of the pipeline uses.

    python3.15t scripts/ecp5_verify_all.py [--workers N] [--device LFE5U-12F]

Exit status is non-zero if any design fails.  Logs to
./tmp/logs/ecp5_verify_all.log as well as the terminal.
"""
import argparse
import concurrent.futures
import glob
import logging
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEF_DBROOT = os.environ.get(
    "TRELLIS_DBROOT", "/home/dan/opt/oss-cad-suite/share/trellis/database")
ECP5_TEST = "/mnt/2tb/git/cynthion-workspace/ecp5-test"

_log_lock = threading.Lock()


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


def find_builds():
    """Build dirs that hold both a top.json and a build_top.sh."""
    out = []
    for cfg in glob.glob(f"{ECP5_TEST}/**/top.config", recursive=True):
        d = os.path.dirname(cfg)
        if (os.path.exists(os.path.join(d, "top.json"))
                and os.path.exists(os.path.join(d, "build_top.sh"))):
            out.append(d)
    return sorted(out)


def verify_one(build_dir, device, dbroot, log):
    """Make the reference pair, then round-trip it.  Returns (name, ok, note)."""
    name = os.path.relpath(build_dir, ECP5_TEST).replace("/", "_")
    ref = os.path.join("tmp/ecp5-ref", name)
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, "scripts/ecp5_make_reference.py", build_dir,
             "--out", ref],
            capture_output=True, text=True)
        if r.returncode != 0:
            return name, False, f"reference generation failed: {r.stderr[-300:]}"

        r = subprocess.run(
            [sys.executable, "scripts/ecp5_roundtrip.py", ref,
             "--device", device, "--dbroot", dbroot],
            capture_output=True, text=True)
        tail = [ln for ln in r.stdout.splitlines()
                if "[" in ln or "ROUND-TRIP" in ln or "recovered in" in ln]

        # Connectivity is a separate claim from placement/INIT — check it too.
        rn = subprocess.run(
            [sys.executable, "scripts/ecp5_net_check.py", ref,
             "--device", device, "--dbroot", dbroot],
            capture_output=True, text=True)
        net_tail = [ln for ln in rn.stdout.splitlines()
                    if any(k in ln for k in ("CONSISTENT", "SPLIT", "FUSED",
                                             "fan-in", "NET CHECK"))]

        with _log_lock:
            log.info("=== %s (%.1fs) ===", name, time.time() - t0)
            for ln in tail + net_tail:
                log.info("  %s", ln.split("INFO ", 1)[-1])

        if r.returncode != 0:
            fail = [ln for ln in r.stdout.splitlines() if "FAILED" in ln]
            return name, False, (fail[-1] if fail else "round-trip failed")
        if rn.returncode != 0:
            fail = [ln for ln in rn.stdout.splitlines() if "FAILED" in ln]
            return name, False, (fail[-1] if fail else "net check failed")
        return name, True, "ok"
    except Exception as e:                                  # noqa: BLE001
        return name, False, f"exception: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--device", default="LFE5U-12F")
    ap.add_argument("--dbroot", default=DEF_DBROOT)
    args = ap.parse_args()

    log = setup_logging("ecp5_verify_all")
    builds = find_builds()
    log.info("%d ECP5 builds found; %d workers; GIL enabled=%s",
             len(builds), args.workers, sys._is_gil_enabled())

    results = []
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(verify_one, b, args.device, args.dbroot, log)
                for b in builds]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())

    log.info("---- summary (%.1fs wall) ----", time.time() - t0)
    npass = sum(1 for _, ok, _ in results if ok)
    for name, ok, note in sorted(results):
        log.info("  %-28s %s%s", name, "PASS" if ok else "FAIL",
                 "" if ok else f"  {note}")
    log.info("%d/%d designs passed round-trip", npass, len(results))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
