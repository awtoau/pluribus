#!/usr/bin/env python3.15t
"""Measure how much of a real ECP5 `.config` the native routing graph resolves.

This is the gate that had to pass before writing the ECP5 lifter: if
globalise_net() cannot place a config arc's endpoints, the union-find has
nothing to union and no net can be recovered.  Run it against a vendor-produced
`.config` and read the failure histogram — the wire-name shapes that fail tell
you exactly which family-specific case is still missing.

    python3.15t scripts/ecp5_arc_coverage.py <config> [--device LFE5U-12F]

Logs to ./tmp/logs/ecp5_arc_coverage.log as well as the terminal.
"""
import argparse
import collections
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain  # noqa: E402  (path set above)

DEF_DBROOT = toolchain.trellis_dbroot()

TILE_RE = re.compile(r"^\.tile\s+(\S+)")
ARC_RE = re.compile(r"^arc:\s+(\S+)\s+(\S+)")


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--device", default="LFE5U-12F")
    ap.add_argument("--dbroot", default=DEF_DBROOT)
    args = ap.parse_args()

    log = setup_logging("ecp5_arc_coverage")
    log.info("device=%s config=%s", args.device, args.config)

    from lifters.ecp5_lift import ECP5Lift
    t0 = time.time()
    lift = ECP5Lift(args.device, dbroot=args.dbroot)
    log.info("routing graph built in %.1fs", time.time() - t0)

    tot = ok = 0
    bad = collections.Counter()
    cur = None
    for line in open(args.config):
        s = line.strip()
        m = TILE_RE.match(s)
        if m:
            cur = lift.tile_rc.get(m.group(1))
            continue
        if cur is None:
            continue
        m = ARC_RE.match(s)
        if not m:
            continue
        r, c = cur
        for nm in (m.group(1), m.group(2)):
            tot += 1
            if lift.gkey(r, c, nm) is not None:
                ok += 1
            else:
                bad[re.sub(r"\d+", "#", nm)] += 1

    log.info("arc endpoints: %d total, %d resolved (%.2f%%), %d failed",
             tot, ok, 100.0 * ok / max(tot, 1), tot - ok)
    for k, v in bad.most_common(20):
        log.info("  UNRESOLVED %-40s %d", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
