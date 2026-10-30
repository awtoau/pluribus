#!/usr/bin/env python3.15t
"""Extra standard pair builds for the IO value table (#168): the IOST-000 family on `in` and `bidir` kinds.  Black box: quartus only.

  python3.15t scripts/cycloneiv_clean_io_std.py [--jobs 12] [--limit-sites N]      # log: tmp/logs/cycloneiv_clean_io_std.log

- Why: the third-party image has only IOST 000 pins; `in` / `bidir` have the 2.5 V base and 3.3-V LVTTL only, so 3.3-V LVCMOS, 3.0-V LVTTL,
  3.0-V LVCMOS and 3.0-V PCI (the other standards with IOST 000 on `out`) are missing for those kinds.
- Pair = the existing base build of the kind (STD 2.5 V) + one build with `IO_STANDARD` replaced; spec builds go to the pair-build tree
  (tmp/cycloneiv_clean/io_pairs/builds/<pin>_<site>/<kind>.STD=<value>), bases are the existing ones.  `io_decode.extra_rows` reads them.
- Sites: the same 24 sampled sites (2 ends + 2 interior per bank); input-only pins skip `bidir` (fitter refuses output there).
- Builds: 4 values x (24 `in` + 20 `bidir`) = 176 (<= 200).
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
VALUES = ("3.3-V LVCMOS", "3.0-V LVTTL", "3.0-V LVCMOS", "3.0-V PCI")      # standards already built on `out` with IOST 000 (docs/cycloneiv-clean-io.md)
KINDS = ("in", "bidir")
log = logging.getLogger("io_std")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--limit-sites", type=int)
    ap.add_argument("--values", default=",".join(VALUES), help="comma list of IO_STANDARD values (default: the IOST-000 family)")
    ap.add_argument("--kinds", default=",".join(KINDS))
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_io_std.log"), mode="a")])
    sample = M.sample_sites()
    jobs = []
    for pin, v in list(sample.items())[:a.limit_sites]:
        aux, _ = M.aux_pins(v["bank"], sample)
        for kind in a.kinds.split(","):
            if kind == "bidir" and not os.path.exists(os.path.join(M.OUT, "builds", f"{pin}_{v['site']}", f"bidir.STD={M.BASE_STD.replace(' ', '_')}", "result.npz")):
                continue                      # input-only pin: the base itself was refused
            for val in a.values.split(","):
                assigns = (("STD", val),)
                jobs.append((os.path.join(M.OUT, "builds", f"{pin}_{v['site']}", M.bid(kind, assigns)), kind, pin, aux, assigns))
    log.info("jobs %d (limit 200), workers %d, limits %s", len(jobs), a.jobs, M.LIMITS)
    assert len(jobs) <= 200, len(jobs)

    def run(j):
        try:
            r = M.build_one(j[0], j[1], j[2], j[3], j[4], M.LIMITS)
        except Exception as e:
            r = f"FAILED exception {e!r}"
        log.info("%s %s: %s", j[2], os.path.basename(j[0]), r)
        return r
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(run, jobs))
    log.info("done: %s", {r.split()[0]: res.count(r) for r in set(res)})


if __name__ == "__main__":
    main()
