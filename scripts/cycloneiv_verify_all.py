#!/usr/bin/env python3.15t
"""Cyclone IV verification, one entry point (same shape as cyclonev_verify_all.py).

Stages (each a subprocess; a stage fails on rc != 0; BLOCKING stages fail the run):
  1 lut_mask   cycloneiv_lut_check.py   every placed LUT mask decoded from CRAM vs the post-fit .vo (BLOCKING, 100%)
  2 routing    removed with the learned tables; returns as the clean P3 gate (#165)
  3 lifted_sim cycloneiv_lifted_sim_check.py  unavailable, pending clean P2 tracer (#165); not run, not counted
  4 not_lifted the lifter's NOT LIFTED list, printed loudly (M9K, multipliers, PLL, transceivers,
               IO routing, clock tree are never counted as matched)

  python3.15t scripts/cycloneiv_verify_all.py [--limit N]
Log tmp/logs/cycloneiv_verify_all.log
"""
import argparse
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "tmp" / "logs" / "cycloneiv_verify_all.log"
# Host-process rule (#53): stall = no output line and no CPU progress for 60 s; the overall limit is
# 3x the measured cold worst case of the stage (measured 2026-10-26 on gx150_sp_* odd half).
STALL_S = 60
POLL_S = 5
OVERALL_S = {"lut_mask": 900, "lifted_sim": 3600}


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def run_stage(name, cmd):
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            errors="replace")
    lines = queue.Queue()

    def pump():
        for ln in proc.stdout:
            lines.put(ln)
        lines.put(None)
    threading.Thread(target=pump, daemon=True).start()
    ps = psutil.Process(proc.pid)
    cpu_last, prog = -1.0, time.monotonic()
    out = []
    while True:
        try:
            ln = lines.get(timeout=POLL_S)
            prog = time.monotonic()
        except queue.Empty:
            try:
                kids = [ps] + ps.children(recursive=True)
                c = sum(sum(p.cpu_times()[:2]) for p in kids)
            except psutil.Error:
                c = cpu_last
            if c > cpu_last:
                cpu_last, prog = c, time.monotonic()
            over = time.monotonic() - t0 > OVERALL_S.get(name, 1800)
            if over or time.monotonic() - prog >= STALL_S:
                proc.kill()
                log(f"[{name}] KILLED: {'overall limit' if over else f'stall {STALL_S}s'}, elapsed "
                    f"{time.monotonic() - t0:.0f}s, loadavg {os.getloadavg()}, last: {out[-1].strip() if out else ''!r}")
                return 124, out
            continue
        if ln is None:
            break
        out.append(ln)
        print(ln, end="", flush=True)
    rc = proc.wait()
    log(f"[{name}] rc={rc} in {time.monotonic() - t0:.0f}s")
    return rc, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="designs per stage (0 = all)")
    ap.add_argument("--skip", default="", help="comma list of stages to skip")
    a = ap.parse_args()
    skip = set(a.skip.split(","))
    py = sys.executable
    results = {}
    if "lut_mask" not in skip:
        rc, _ = run_stage("lut_mask", [py, "scripts/cycloneiv_lut_check.py", "--designs", "gx150_*", "--workers", "2"])
        results["lut_mask"] = (rc, True)
    log("routing: removed with the learned tables (#165); lifted_sim: unavailable, pending clean P2 tracer (#165); neither ran")
    log("NOT LIFTED (never counted as matched): M9K / M144K memories, embedded multipliers, PLL, transceivers, "
        "IO-row routing and pad enables, clock tree, carry chains entering a LAB at LE 0")
    bad = [k for k, (rc, blocking) in results.items() if rc and blocking]
    for k, (rc, blocking) in results.items():
        log(f"STAGE {k}: {'ok' if rc == 0 else 'FAIL'}{' (blocking)' if blocking else ' (reported)'}")
    log("RESULT: " + ("PASS" if not bad else f"FAIL blocking stages {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
