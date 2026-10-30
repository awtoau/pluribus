#!/usr/bin/env python3.15t
"""Unused-pin state builds (#168): which CFF bits does each global unused-pin option set at every IO site?  Black box: quartus only.

  python3.15t scripts/cycloneiv_clean_io_unused.py [--pins AD25,C29,A23]      # log: tmp/logs/cycloneiv_clean_io_unused.log

- Pair = base (`AS INPUT TRI-STATED`, the pair-build default, in cycloneiv_clean_io_pairs builds) vs the same `out` design with one
  other RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP value.  One build changes every unused site at once (456 sites); 3 pins = site-independence check.
- Builds: 3 options x pins (<= 200 builds, recovery-process sampling plan: the option is global, pins span 3 banks).
- Output: tmp/cycloneiv_clean/io_unused/<pin>/<option tag>/result.npz (same layout as the pair builds).
"""
import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cycloneiv_clean_io_pairs as M  # noqa: E402

REPO = M.REPO
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "io_unused")
# source: Quartus QSF RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP legal values (Assignment Editor, "Reserve all unused pins")
OPTIONS = {"pullup": "AS INPUT TRI-STATED WITH WEAK PULL-UP", "gnd": "AS OUTPUT DRIVING GROUND", "unspec": "AS OUTPUT DRIVING AN UNSPECIFIED SIGNAL"}
BASE_OPTION = "AS INPUT TRI-STATED"
log = logging.getLogger("io_unused")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pins", default="AD25,C29,A23")
    ap.add_argument("--jobs", type=int, default=9)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_io_unused.log"), mode="a")])
    sample = M.sample_sites()
    jobs = []
    for pin in a.pins.split(","):
        aux, _ = M.aux_pins(sample[pin]["bank"], sample)
        for name, opt in OPTIONS.items():
            jobs.append((os.path.join(OUT, pin, name), pin, aux, opt))
    log.info("jobs %d (limit 200), workers %d, limits %s", len(jobs), a.jobs, M.LIMITS)

    def run(j):
        try:
            r = M.build_one(j[0], "out", j[1], j[2], (("STD", M.BASE_STD),), M.LIMITS, reserve=j[3])
        except Exception as e:
            r = f"FAILED exception {e!r}"
        log.info("%s %s: %s", j[1], os.path.basename(j[0]), r)
        return r
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(run, jobs))
    log.info("done: %s", res)


if __name__ == "__main__":
    main()
