#!/usr/bin/env python3.15t
"""Split the register claims of reg_used by claim reason x clock-source availability x ground truth (#165).

  python3.15t scripts/cycloneiv_clean_regclaim_split.py [--tier full] [--prefix hl_] [--limit N]
reason: sync (LE_USE_SYNC_* both set) / regbuf (used buffer selects register) / local (no buffer used, YGR[2] = 0).
clock: ffctl LAB clock mux of the LE's LE_CLOCK_SELECT group decodes to a source (clk_sel >= 0).  gt: vo has a dffeas at the site.
Log tmp/logs/regclaim_split.log.
"""
import argparse
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_gate as G  # noqa: E402
from lifters.cycloneiv_clean import tracer as T  # noqa: E402

log = logging.getLogger("regclaim_split")


def split(cx, d):
    bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
    fired = cx.ext.apply(bits, cx.st.fire(bits, workers=2))
    rg = cx.ext.reg
    e = fired[G.HEADLINE]
    u = rg.used(e).any(axis=-1)
    sy = (bits[rg.sync[0]] == 1) & (bits[rg.sync[1]] == 1)
    ff = rg.ff(bits, e)
    sig = cx.ffc.lab_signals(bits)
    grp = cx.ffc.le_val(bits)["LE_CLOCK_SELECT"].astype(np.int64)
    csel = np.take_along_axis(sig["clk_sel"], grp, axis=1)
    _, lcs, ffs = G.parse_vo(os.path.join(d, "postfit.vo"))
    gts = {(cx.lut.lab(x, y), n) for (x, y, n) in ffs.values()}
    arith = {(cx.lut.lab(x, y), n): L["arith"] for (x, y, n), L in lcs.items()}
    out = collections.Counter()
    for i, n in np.argwhere(ff).tolist():
        reason = "sync" if sy[i, n] else ("local" if not u[i, n] else "regbuf")
        out[("GT" if (i, n) in gts else "EXTRA", reason, "clk" if csel[i, n] >= 0 else "noclk", "arith" if arith.get((i, n)) else "plain")] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="full")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "regclaim_split.log"), "w")])
    ds = [d for d in G.tier_designs(a.tier) if os.path.basename(d).startswith(a.prefix)]
    ds = ds[:a.limit] if a.limit else ds
    cx = G.Ctx()
    tot = collections.Counter()
    for d in ds:
        tot.update(split(cx, d))
    for k, v in sorted(tot.items()):
        log.info("%7d  %s", v, k)


if __name__ == "__main__":
    main()
