#!/usr/bin/env python3.15t
"""#186: does the DJI m2001 image's LE/carry-chain packing density look uniform across the die, or does
it show a discontinuity suggesting different regions were compiled/placed under different settings?
Read-only on an existing lift pickle -- no new build, no decoder/emit change. Coarse 8x8 (x,y) bucket
LUT count and carry-chain-mode fraction; a real settings seam (if it existed) would show as a sharp
step between buckets, not a gradual gradient (die-edge IO/routing effects are expected and gradual).

  python3.15t scripts/cycloneiv_clean_regional_utilization.py tmp/image_sim_dji_push/nl.pkl
Log tmp/logs/cycloneiv_clean_regional_utilization.log.
"""
import collections
import json
import logging
import os
import pickle
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
log = logging.getLogger("regional_utilization")
BUCKET = 15   # ~die/8 for a 116x92-ish Cyclone IV GX150 LAB grid; coarse enough to be statistically meaningful per bucket


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "tmp/image_sim_dji_push/nl.pkl"
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_regional_utilization.log"))])
    nl = pickle.load(open(path, "rb"))
    buckets = collections.defaultdict(lambda: [0, 0])   # (bx,by) -> [n_luts, n_carry]
    for L in nl.luts:
        bx, by = L["x"] // BUCKET, L["y"] // BUCKET
        buckets[(bx, by)][0] += 1
        if L["mode"] == "cin":
            buckets[(bx, by)][1] += 1
    rows = []
    for (bx, by), (n, c) in sorted(buckets.items()):
        frac = c / n if n else 0.0
        rows.append(dict(bx=bx, by=by, n_luts=n, n_carry=c, carry_frac=round(frac, 3)))
    fracs = [r["carry_frac"] for r in rows if r["n_luts"] >= 50]   # ignore sparse edge buckets, too noisy to judge
    mean = sum(fracs) / len(fracs) if fracs else 0.0
    var = sum((f - mean) ** 2 for f in fracs) / len(fracs) if fracs else 0.0
    sd = var ** 0.5
    outliers = [r for r in rows if r["n_luts"] >= 50 and abs(r["carry_frac"] - mean) > 3 * sd]
    result = dict(n_buckets=len(rows), bucket_size=BUCKET, carry_frac_mean=round(mean, 3), carry_frac_sd=round(sd, 3),
                  n_outlier_buckets_3sigma=len(outliers), outliers=outliers, rows=rows)
    log.info("mean carry_frac=%.3f sd=%.3f outliers(>3sigma)=%d / %d buckets", mean, sd, len(outliers), len(rows))
    out = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_regional_utilization_result.json")
    json.dump(result, open(out, "w"), indent=1)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
