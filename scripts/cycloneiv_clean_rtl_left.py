#!/usr/bin/env python3.15t
"""Classify the LUTs the RTL lift leaves flat (rule FLAT_LUT) by chain failure reason and shape (#165).

  python3.15t scripts/cycloneiv_clean_rtl_left.py --image IMAGE      build + cache the netlist (tmp/rtl/image_nl.pkl), classify
  python3.15t scripts/cycloneiv_clean_rtl_left.py                    classify from the cache
Counts only.  Log tmp/logs/cycloneiv_clean_rtl_left.log, result tmp/cycloneiv_clean/rtl_left.json.
"""
import argparse
import collections
import json
import logging
import os
import pickle
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("cycloneiv_clean_rtl_left")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_rtl_left.log")
CACHE = os.path.join(REPO, "tmp", "rtl", "image_nl.pkl")
PLANE = os.path.join(REPO, "tmp", "cycloneiv_clean", "rtl_left_plane.rbf")


def build(image):
    import cycloneiv_decompress as cd
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    os.makedirs(os.path.dirname(PLANE), exist_ok=True)
    open(PLANE, "wb").write(cd.decompress(open(image, "rb").read(), {}))
    try:
        with heavy_guard.lease(heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"], "rtl_left", log):
            nl = emit.Builder(emit.Ctx(), PLANE, "image").run()
    finally:
        os.remove(PLANE)
    pickle.dump(nl, open(CACHE, "wb"))
    return nl


def classify(nl):
    from lifters.cycloneiv_clean import rtl
    L = rtl.Lift(nl)
    L.run()
    res = collections.Counter()
    shape = collections.Counter()
    bylen = collections.defaultdict(collections.Counter)
    seen = set()
    for n in L.need_opaque:
        ent = L.chain_of.get(n)
        if ent is None:
            res["opaque_not_in_chain"] += 1
            continue
        ch = ent[0]
        if ch["k"] in seen:
            continue
        seen.add(ch["k"])
        why = ch.get("why", "?")
        res[why] += len(ch["luts"])
        bylen[why][min(len(ch["luts"]), 33)] += 1
        used = sum(1 for x in ch["luts"] if L.fan[x["name"]])
        shape[(why, "sum_used" if used else "sum_unused")] += len(ch["luts"])
    out = dict(luts=len(nl.luts), opaque=len(L.need_opaque), chains_failed=len(seen), by_reason=dict(res),
               shape={f"{k[0]}/{k[1]}": v for k, v in shape.items()}, length_hist={k: dict(sorted(v.items())) for k, v in bylen.items()})
    log.info("%s", json.dumps(out))
    os.makedirs(os.path.join(REPO, "tmp", "cycloneiv_clean"), exist_ok=True)
    json.dump(out, open(os.path.join(REPO, "tmp", "cycloneiv_clean", "rtl_left.json"), "w"), indent=1)
    return L


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    nl = build(a.image) if a.image else pickle.load(open(CACHE, "rb"))
    classify(nl)


if __name__ == "__main__":
    main()
