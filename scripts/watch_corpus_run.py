#!/usr/bin/env python3
"""Watch the ECP5 corpus run: report progress, memory pressure, and exit.

Lifting an LFE5U-85F design holds the whole routing graph plus the union-find,
so a wide --workers setting can exhaust RAM: eight concurrent 85F lifts drove
this machine to zero free memory and the run had to be killed at 104/228.
This emits one line per meaningful change so the run can be left alone without
either polling it by hand or discovering an OOM after the fact.

Prints (and therefore notifies) on:
  * every N completed files
  * available memory dropping below a floor
  * the run exiting

Usage:
    python3 scripts/watch_corpus_run.py [--every 10] [--floor-mb 5000]
"""
import argparse
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(REPO, "tmp", "logs", "ecp5_corpus_test.log")


def available_mb():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return None


def running():
    """True if a corpus-test process is alive.

    Matches the script name in the cmdline rather than shelling out to pgrep:
    a pgrep pattern broad enough to catch the run also matches this watcher
    and any monitor wrapping it, which is how an earlier `pkill -f` took out
    its own observers.
    """
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or pid == str(os.getpid()):
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        if "ecp5_corpus_test.py" in cmd:
            return True
    return False


def counts():
    if not os.path.exists(LOG):
        return 0, 0, 0
    lines = open(LOG, errors="replace").read().splitlines()
    starts = [i for i, l in enumerate(lines) if "testing" in l and "bitstreams" in l]
    cur = lines[starts[-1]:] if starts else lines
    ok = sum(1 for l in cur if "decode=ok" in l)
    fail = sum(1 for l in cur
               if re.search(r"DECODE-FAIL|ORACLE-DIFF|LIFT-FAIL|UNIDENTIFIED", l))
    total = 0
    if starts:
        m = re.search(r"testing (\d+) bitstreams", lines[starts[-1]])
        if m:
            total = int(m.group(1))
    return ok, fail, total


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--every", type=int, default=10)
    ap.add_argument("--floor-mb", type=int, default=5000)
    ap.add_argument("--poll", type=float, default=20.0)
    args = ap.parse_args()

    last_bucket = -1
    last_fail = 0
    warned_low = False
    while True:
        ok, fail, total = counts()
        avail = available_mb()

        if fail > last_fail:
            print(f"FAILURES: {fail} (was {last_fail}) at {ok}/{total}",
                  flush=True)
            last_fail = fail

        bucket = ok // args.every
        if bucket != last_bucket:
            print(f"progress {ok}/{total} complete, {fail} failures, "
                  f"{avail} MB free", flush=True)
            last_bucket = bucket

        if avail is not None and avail < args.floor_mb:
            if not warned_low:
                print(f"LOW MEMORY: {avail} MB available at {ok}/{total} "
                      f"- OOM risk, consider fewer --workers", flush=True)
                warned_low = True
        else:
            warned_low = False

        if not running():
            print(f"corpus run exited at {ok}/{total}, {fail} failures",
                  flush=True)
            return 0
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
