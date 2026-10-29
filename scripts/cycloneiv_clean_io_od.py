#!/usr/bin/env python3.15t
"""Open-drain check for the IO pair builds (#168): does a constant-0-data tri-state set CFF / CRAM bits that a plain tri-state does not?

  python3.15t scripts/cycloneiv_clean_io_od.py [--pins AD25,C29,A23]      # log: tmp/logs/cycloneiv_clean_io_od.log

- QSF `AUTO_OPEN_DRAIN_PINS` is a detection switch (default ON), not a per-pin forced mode: a pin is open-drain when its logic is a
  tri-state with constant-0 data (decompile: ASM_IO_PIN_MODE::process_atom picks mux 3 / 4 from atom bit 0x16, docs/cycloneiv-clean-io.md).
- Builds per pin (STD 2.5 V, pin and aux pins as in cycloneiv_clean_io_pairs.py): tri (data = a & c), od (data = 0), od_off (data = 0, assignment OFF).
- Result file: tmp/cycloneiv_clean/io_od/result.json (pin -> {build pair -> CFF / CRAM diff counts and IO group names}).
"""
import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cycloneiv_clean_io_pairs as M  # noqa: E402

REPO = M.REPO
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "io_od")
log = logging.getLogger("io_od")
M.KINDS["od"] = "output p, input a, input c, input e, output y"
M.BODY["od"] = "assign p = e ? 1'bz : 1'b0; assign y = a ^ c ^ e;"
BUILDS = {"tri": ("tri", (("STD", M.BASE_STD),)), "od": ("od", (("STD", M.BASE_STD),)),
          "od_off": ("od", (("STD", M.BASE_STD), ("OD", "OFF")))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pins", default="AD25,C29,A23")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_io_od.log"), mode="a")])
    sample = M.sample_sites()
    jobs = []
    for pin in a.pins.split(","):
        aux, _ = M.aux_pins(sample[pin]["bank"], sample)
        for name, (kind, assigns) in BUILDS.items():
            jobs.append((os.path.join(OUT, pin, name), kind, pin, aux, assigns))

    def run(j):
        try:
            r = M.build_one(j[0], j[1], j[2], j[3], j[4], M.LIMITS)
        except Exception as e:
            r = f"FAILED exception {e!r}"
        log.info("%s %s: %s", j[2], os.path.basename(j[0]), r)
        return r
    with ThreadPoolExecutor(len(jobs)) as ex:
        list(ex.map(run, jobs))
    res = {}
    for pin in a.pins.split(","):
        b = {n: M.load_build(os.path.join(OUT, pin), n) for n in BUILDS}
        res[pin] = {}
        for x, y in (("tri", "od"), ("od", "od_off"), ("tri", "od_off")):
            if b[x] is None or b[y] is None:
                res[pin][f"{x}->{y}"] = "missing build"
                continue
            cff = np.nonzero(b[x]["cff"] != b[y]["cff"])[0].tolist()
            cram = np.nonzero(np.unpackbits(b[x]["cram"] ^ b[y]["cram"], bitorder="little"))[0].tolist()
            res[pin][f"{x}->{y}"] = {"cff": cff, "n_cram": len(cram), "cram": cram[:400], "pin": [b[x]["pin"], b[y]["pin"]]}
        log.info("%s %s", pin, {k: (v if isinstance(v, str) else (len(v["cff"]), v["n_cram"])) for k, v in res[pin].items()})
    json.dump(res, open(os.path.join(OUT, "result.json"), "w"))


if __name__ == "__main__":
    main()
