#!/usr/bin/env python3.15t
"""Where the 32-bit whole-stream CRC sits in the rbf (docs/altera/cycloneIV/cycloneiv-manual-review.md F3, #169).  Black box: quartus_map/fit/asm/cpf only.

  python3.15t scripts/cycloneiv_clean_crc_loc.py build      # 3 builds: BASE, CRC_ERROR_CHECKING ON, ON + divisor 256 (full rbf kept)
  python3.15t scripts/cycloneiv_clean_crc_loc.py analyse    # rbf byte diffs of the pairs, outside / inside the option cells
Log: tmp/logs/cycloneiv_clean_crc_loc.log; builds + rbf: tmp/cycloneiv_clean/crc_loc/
"""
import argparse
import logging
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cycloneiv_clean_option_pairs as OP  # noqa: E402

REPO = OP.REPO
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "crc_loc")
BUILDS = (("BASE", None), ("crc_on", (("CRC_ERROR_CHECKING", "ON"),)),
          ("crc_on_div_256", (("CRC_ERROR_CHECKING", "ON"), ("ERROR_CHECK_FREQUENCY_DIVISOR", "256"))))     # 3 builds (limit 3)
log = logging.getLogger("crc_loc")


def cmd_build(_a):
    os.makedirs(OUT, exist_ok=True)
    for name, assign in BUILDS:
        r = OP.build_one(os.path.join(OUT, name), "min", assign, None, OP.aux_pins(OP.BASES["min"][2]), keep_rbf=os.path.join(OUT, name + ".rbf"))
        log.info("%s: %s", name, r)


def cmd_analyse(_a):
    base = np.fromfile(os.path.join(OUT, "BASE.rbf"), np.uint8)
    for name, _ in BUILDS[1:]:
        o = np.fromfile(os.path.join(OUT, name + ".rbf"), np.uint8)
        same = len(o) == len(base)
        d = np.nonzero(o[:len(base)] != base[:len(o)])[0] if same else None
        log.info("%s: size %d vs %d, differing bytes %s", name, len(o), len(base), None if d is None else len(d))
        if d is not None:
            log.info("%s: positions %s", name, d[:80].tolist())
            log.info("%s: first diff < header (75 B): %s, in frames region: %s", name, d[d < OP.HEADER_BYTES].tolist(), d[d >= OP.HEADER_BYTES].tolist()[:40])


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_crc_loc.log"), mode="a")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("build").set_defaults(f=cmd_build)
    sp.add_parser("analyse").set_defaults(f=cmd_analyse)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
