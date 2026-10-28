#!/usr/bin/env python3.15t
"""Run a command, report wall and peak PSS summed over its process tree (A/B for #149).

  python3.15t scripts/ab_measure.py [--lease-gb G] [--json OUT] -- CMD ARGS...

PSS (not RSS) so shared pages of a process tree are counted once.  Samples every 0.2 s:
a lift peak lasts seconds.  Log: tmp/logs/ab_measure.log.
"""
import argparse
import contextlib
import json
import os
import subprocess
import sys
import threading
import time

import psutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
SAMPLE_S = 0.2


def tree_pss_gb(root):
    tot = 0
    try:
        procs = [root, *root.children(recursive=True)]
    except psutil.Error:
        return 0.0
    for p in procs:
        try:
            tot += p.memory_full_info().pss
        except psutil.Error:
            pass
    return tot / 2**30


def main():
    argv = sys.argv[1:]
    cmd = argv[argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--lease-gb", type=float, default=0.0,
                    help="outer lease; 0 = none (the command leases per job itself)")
    ap.add_argument("--json")
    a = ap.parse_args(argv[:argv.index("--")])
    import heavy_guard
    lg = heavy_guard.stdout_log()
    with (heavy_guard.lease(a.lease_gb, "ab_measure", lg) if a.lease_gb else contextlib.nullcontext()):
        t0 = time.monotonic()
        p = subprocess.Popen(cmd, cwd=REPO)
        root = psutil.Process(p.pid)
        peak = [0.0]
        stop = threading.Event()

        def sample():
            while not stop.wait(SAMPLE_S):
                peak[0] = max(peak[0], tree_pss_gb(root))
        th = threading.Thread(target=sample)
        th.start()
        rc = p.wait()
        stop.set()
        th.join()
        wall = time.monotonic() - t0
    r = dict(cmd=cmd, rc=rc, wall_s=round(wall, 1), peak_pss_gb=round(peak[0], 2))
    print(json.dumps(r))
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    with open(os.path.join(REPO, "tmp", "logs", "ab_measure.log"), "a") as fh:
        fh.write(time.strftime("%Y-%m-%dT%H:%M:%S%z ") + json.dumps(r) + "\n")
    if a.json:
        json.dump(r, open(a.json, "w"))
    sys.exit(rc)


if __name__ == "__main__":
    main()
