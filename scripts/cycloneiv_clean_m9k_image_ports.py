#!/usr/bin/env python3.15t
"""M9K port/mode decode counts of the third-party image (#165, #169): counts only (env PLURIBUS_DJI_IMAGE = the .bin/.rbf path).

  python3.15t scripts/cycloneiv_clean_m9k_image_ports.py        log: tmp/logs/cycloneiv_clean_m9k_image_ports.log
Used tile = any connected data / address / byte-enable / write-enable group, or any content bit set.  Per used tile: width class, ports (data, address, pia),
mode bits (true dual port, packed, output register).
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
    logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_m9k_image_ports.log")), logging.StreamHandler()])
log = logging.getLogger("m9k_image_ports")


def main():
    path = os.environ.get("PLURIBUS_DJI_IMAGE")
    if not path or not os.path.exists(path):
        raise SystemExit("PLURIBUS_DJI_IMAGE not set or missing")
    from lifters.cycloneiv_clean import emit
    cx = emit.Ctx()
    nl = emit.Builder(cx, path, "image", 2).run()
    cnt = collections.Counter()
    for m in nl.m9k:
        cnt["m9k_tiles_with_ports"] += 1
        cnt["modelled_single_port"] += int(bool(m.get("modelled")))
        cnt[f"cls_{m.get('cls')}"] += 1
        cnt[f"W_{m.get('W')}"] += 1
        cnt["why: " + str(m.get("why", "")).split(" (")[0]] += 0 if m.get("modelled") else 1
        for name, v in m.get("ctl", {}).items():
            cnt[f"{name}_set"] += int(v)
        cnt["content_nonzero"] += int(bool(m["content"].any())) if "content" in m else 0
    log.info("tiles %d", len(nl.m9k))
    for k in sorted(cnt):
        log.info("  %s %d", k, cnt[k])


if __name__ == "__main__":
    main()
