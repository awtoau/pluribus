#!/usr/bin/env python3.15t
"""Differential-output pair builds for the IO tables (#168): which sites change when a `p` pin is a true LVDS / mini-LVDS input?  Quartus only.

  python3.15t scripts/cycloneiv_clean_io_lvds.py [--pins AG18,A23,G14] [--jobs 9]      # log: tmp/logs/cycloneiv_clean_io_lvds.log

- Why: 6 sites of the third-party image carry stray strength / IOST bits on DIFFIO pads next to no decoded single-ended setting.
- Pair per pin = base (2.5 V, kind `in`) vs the same design with IO_STANDARD LVDS / mini-LVDS (the `n` pad is placed by the fitter).
- Builds: pins x (base + 2 standards) = 9 (<= 200).  Output: tmp/cycloneiv_clean/io_lvds_<kind>/<pin>/<tag>/result.npz.
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
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "io_lvds")      # + "_<kind>"
# source: Quartus IO_STANDARD names (Assignment Editor); the *_E_* ones are the IOST value 3 / 11 dirt entries (io_dirt: RSDS_1R / _3R, PPDS_3R, MINI_LVDS_3R = 3)
STANDARDS = {"base": "2.5 V", "lvds": "LVDS", "minilvds": "mini-LVDS", "rsds3r": "RSDS_E_3R", "mini3r": "mini-LVDS_E_3R", "ppds3r": "PPDS_E_3R", "rsds1r": "RSDS_E_1R"}
log = logging.getLogger("io_lvds")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pins", default="AG18,A23,G14")
    ap.add_argument("--jobs", type=int, default=9)
    ap.add_argument("--tags", default="base,lvds,minilvds", help="comma list of STANDARDS keys")
    ap.add_argument("--kind", default="in", help="design kind; LVDS on `out` is refused by the fitter at these locations (input pins only)")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_io_lvds.log"), mode="a")])
    pins = M.load_pins()
    jobs = []
    for pin in a.pins.split(","):
        aux, _ = M.aux_pins(pins[pin]["bank"], {pin: pins[pin]})
        for tag in a.tags.split(","):
            std = STANDARDS[tag]
            jobs.append((os.path.join(OUT + "_" + a.kind, pin, tag), pin, aux, (("STD", std),)))
    log.info("jobs %d (limit 200), workers %d, limits %s", len(jobs), a.jobs, M.LIMITS)

    def run(j):
        try:
            r = M.build_one(j[0], a.kind, j[1], j[2], j[3], M.LIMITS)
        except Exception as e:
            r = f"FAILED exception {e!r}"
        log.info("%s %s: %s", j[1], os.path.basename(j[0]), r)
        return r
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(run, jobs))
    log.info("done: %s", res)


if __name__ == "__main__":
    main()
