#!/usr/bin/env python3.15t
"""Fast lifter iteration on cached hl netlists (#165): train = even seeds, held-out = odd seeds.

  python3.15t scripts/cycloneiv_hl_iter.py --dump            build + pickle every hl netlist (tmp/rtl/hl_nl/, needs the emit; ~10 min)
  python3.15t scripts/cycloneiv_hl_iter.py --split train     lift + score (counts per key, no simulation); --split heldout / both
  python3.15t scripts/cycloneiv_hl_iter.py --split train --kinds counter,fsm --show counters   print per-design truth vs recovered
Scoring = cycloneiv_hl_score.score_one / summarise (same keys).  Held-out is only run for before / after reports, never while changing rtl.py.
Log tmp/logs/cycloneiv_hl_iter.log.
"""
import argparse
import json
import logging
import os
import pickle
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("cycloneiv_hl_iter")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_hl_iter.log")
CACHE = os.path.join(REPO, "tmp", "rtl", "hl_nl")
ROOT = os.path.join(REPO, "corpus", "cycloneiv")


def seed_of(name):
    return int(re.search(r"_(\d+)$", name)[1])


def dump():
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    os.makedirs(CACHE, exist_ok=True)
    names = sorted(n for n in os.listdir(ROOT) if n.startswith("hl_") and os.path.exists(os.path.join(ROOT, n, "bitstream.rbf")))
    with heavy_guard.lease(heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"], "hl_iter_dump", log):
        cx = emit.Ctx()
        for n in names:
            try:
                nl = emit.Builder(cx, os.path.join(ROOT, n, "bitstream.rbf"), n).run()
                flat = emit.verilog(nl)
            except SystemExit as e:
                log.error("%s: %s", n, e)
                continue
            pickle.dump((nl, flat), open(os.path.join(CACHE, n + ".pkl"), "wb"))
            log.info("dumped %s", n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--split", default="train", choices=("train", "heldout", "both"))
    ap.add_argument("--kinds")
    ap.add_argument("--show")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    if a.dump:
        return dump()
    import cycloneiv_hl_score as S
    from lifters.cycloneiv_clean import rtl
    rows = []
    for f in sorted(os.listdir(CACHE)):
        n = f[:-4]
        sd = seed_of(n)
        if (a.split == "train" and sd % 2) or (a.split == "heldout" and not sd % 2):
            continue
        tr = json.load(open(os.path.join(ROOT, n, "src", "hl_truth.json")))
        if a.kinds and tr["kind"] not in a.kinds.split(","):
            continue
        nl, flat = pickle.load(open(os.path.join(CACHE, f), "rb"))
        text, rep = rtl.lift(nl)
        r = dict(design=n, kind=tr["kind"], eq_flat="n/a", report=rep, score=S.score_one(os.path.join(ROOT, n), rep, tr))
        rows.append(r)
        if a.show:
            exp = tr["expected"]
            log.info("%s expected %s got %s", n, {k: exp.get(k, 0) for k in (a.show.split(","))}, {k: S.recovered(rep)[k] for k in a.show.split(",")})
    s = S.summarise(rows)
    for k, v in s["by_key"].items():
        log.info("KEY %-14s %5d %5d %5d %3d  %.1f%%", k, v["matched"], v["missing"], v["extra"], v["wrong"], v["headline"])
    log.info("OVERALL %s designs %d", s["overall"], s["designs"])
    json.dump(s, open(os.path.join(REPO, "tmp", "cycloneiv_clean", f"hl_iter_{a.split}.json"), "w"), default=str)


if __name__ == "__main__":
    main()
