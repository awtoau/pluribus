#!/usr/bin/env python3
"""Plan a set of test bitstreams that exercise a share of the FPGA fabric.

WHY
---
Nothing in the open flow tests fabric FUNCTION.  SED/SEDGA CRCs the
configuration memory -- it catches a flipped config bit, not a dead LUT or a
broken wire.  Vendor test vectors are proprietary.  So an owner of a board has
no way to ask "is this die actually good?", which matters most for parts where
that is a live question (see the LFE5U-12F/25F same-die work).

Pluribus already knows the fabric exhaustively, so it can plan the test.  This
does the planning half: it reads the device database, counts what there is to
cover, and reports how much of it N bitstreams can reach.

DELIBERATELY NOT EXHAUSTIVE
---------------------------
Full interconnect coverage is a set-cover problem over millions of arcs and is
bounded below by the worst mux fan-in.  That is the wrong target for a
confidence check someone else runs on their own board.  The useful fact is the
shape of the curve: on ECP5 the fan-in median is 20 and p95 is 24, but the
maximum is 64 -- so a couple of dozen configurations reach most of the fabric
and the long tail costs far more for very little.  `--plan` prints that
trade-off so a user picks a point on it knowingly.

WHAT ONE CONFIGURATION CAN COVER
--------------------------------
A PIP is a mux selection: per destination wire, exactly one source may be
active per configuration.  That mutual exclusion is the ONLY thing forcing
extra bitstreams -- bel pins and wires ride along in parallel, because a LUT in
one tile and a LUT in another are exercised simultaneously.

    python3 scripts/fabric_coverage_plan.py --device LFE5U-12F
    python3 scripts/fabric_coverage_plan.py --device LCMXO2-1200 --plan 24

Logs to ./tmp/logs/fabric_coverage_plan.log.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import toolchain  # noqa: E402


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("fabric_coverage_plan")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "fabric_coverage_plan.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def family_of(device, dbroot):
    dj = json.load(open(os.path.join(dbroot, "devices.json")))
    for fam, blk in dj["families"].items():
        if device in blk.get("devices", {}):
            return fam
    raise SystemExit(f"device {device!r} not found in {dbroot}/devices.json")


def mux_fanin(dbroot, family):
    """{(tiletype, dest_wire): fan-in} read from the tile database.

    Per TILE TYPE, not per instance: every PLC2 tile shares one mux structure,
    so covering a mux arc in one tile covers that arc's *shape* everywhere. That
    is the right granularity for a confidence check -- per-instance coverage is
    the exhaustive problem this deliberately is not.
    """
    tdir = os.path.join(dbroot, family, "tiledata")
    fan = {}
    for tt in sorted(os.listdir(tdir)):
        p = os.path.join(tdir, tt, "bits.db")
        if not os.path.isfile(p):
            continue
        dest, n = None, 0
        for ln in open(p, errors="ignore"):
            if ln.startswith(".mux"):
                if dest:
                    fan[dest] = n
                parts = ln.split()
                dest = (tt, parts[1]) if len(parts) > 1 else None
                n = 0
            elif ln.startswith("."):
                if dest:
                    fan[dest] = n
                dest = None
            elif dest is not None and ln.strip():
                n += 1
        if dest:
            fan[dest] = n
    return fan


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="LFE5U-12F")
    ap.add_argument("--plan", type=int, default=None,
                    help="report coverage for exactly this many bitstreams")
    ap.add_argument("--dbroot", default=None)
    args = ap.parse_args()
    log = setup_logging()

    dbroot = args.dbroot or toolchain.trellis_dbroot()
    family = family_of(args.device, dbroot)
    log.info("device %s  family %s  db %s", args.device, family, dbroot)

    fan = mux_fanin(dbroot, family)
    if not fan:
        raise SystemExit(f"no .mux entries found under {dbroot}/{family}/tiledata")
    vals = sorted(fan.values())
    total = sum(vals)
    log.info("mux destinations %d   routing arcs %d", len(vals), total)
    log.info("fan-in  mean %.1f  median %d  p95 %d  MAX %d",
             total / len(vals), vals[len(vals) // 2],
             vals[int(len(vals) * .95)], vals[-1])

    # A configuration can select ONE source per destination, so N configurations
    # cover min(N, fan-in) arcs of each destination.  This is the upper bound a
    # perfect packer reaches; a real generator does worse and should be measured
    # against it rather than assumed equal to it.
    def covered(n):
        return sum(min(n, f) for f in vals)

    if args.plan:
        c = covered(args.plan)
        log.info("PLAN %d bitstreams -> %d/%d arcs (%.1f%%)",
                 args.plan, c, total, 100 * c / total)
        return 0

    log.info("")
    log.info("bitstreams   arcs covered        share")
    for n in (1, 2, 4, 8, 12, 16, 20, 24, 32, 48, vals[-1]):
        c = covered(n)
        bar = "#" * int(40 * c / total)
        log.info("%9d   %11s   %5.1f%%  %s", n, f"{c:,}", 100 * c / total, bar)
    log.info("")
    log.info("The knee is the point worth picking: most of the fabric costs a "
             "couple of dozen configurations, the last few per cent costs "
             "several times that.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
