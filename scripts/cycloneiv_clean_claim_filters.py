#!/usr/bin/env python3.15t
"""Register claims removed by each reg_used filter, by class, on corpus designs (with ground truth) or the image (env PLURIBUS_DJI_IMAGE) (#165).

  python3.15t scripts/cycloneiv_clean_claim_filters.py --tier full [--prefix hl_] [--limit N]
  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_claim_filters.py --image
stage: kept / drop_clock (no decodable LAB clock source) / drop_local (local-path claim whose LOCAL_LINE has no consumer); a claim dropped by both counts as drop_clock.
class: reason (sync / regbuf / local) x arith (LE has a LUT with carry-in) x lut (INIT set).  Corpus rows add gt (vo has a dffeas at the site).  Counts only.
Log tmp/logs/claim_filters.log.
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

log = logging.getLogger("claim_filters")


def classes(cx, bits, gts=None):
    rg = cx.ext.reg
    e = cx.ext.apply(bits, cx.st.fire(bits, workers=2))[G.HEADLINE]
    y = np.stack([bits[c] == 1 for c in rg.ygr], axis=-1)
    u = rg.used(e)
    nz = cx.lut.cells(bits).sum(axis=2) > 0
    sy1 = bits[rg.sync[0]] == 1
    sync = sy1 & (bits[rg.sync[1]] == 1)
    cfg = nz | sync
    reg_buf = (u & ~y[..., :2]).any(axis=-1)
    local_raw = ~u.any(axis=-1) & ~y[..., 2]
    lused = rg.local_used(bits, e, cfg | sy1)
    claim0 = sync | (cfg & (reg_buf | local_raw))
    ck = rg.clock_ok(bits)
    carry = cx.lut.carry_in(bits)
    out = collections.Counter()
    fb = cx.ffc.le_val(bits)["LE_USE_REGISTER_FEEDBACK"] == 1
    cont = np.zeros_like(carry)                                  # next LE of the same LAB is in carry mode (chain continues)
    cont[:, :-1] = carry[:, 1:]
    # consumer kind of a local-path claim: edge = programmed edge leaves LOCAL_LINE; pin = LE_LUT_INPUT pin of a live LE selects it
    src = np.zeros(cx.rt.n, bool)
    src[cx.st.esrc[np.asarray(e, np.int64)]] = True
    cedge = (rg.ll >= 0) & src[np.maximum(rg.ll, 0)]
    for i, n in np.argwhere(claim0).tolist():
        reason = "sync" if sync[i, n] else ("regbuf" if reg_buf[i, n] else "local")
        if not ck[i, n]:
            stage = "drop_clock"
        elif reason == "local" and not lused[i, n]:
            stage = "drop_local"
        else:
            stage = "kept"
        k = (stage, reason, "arith" if carry[i, n] and nz[i, n] else "plain", "lut" if nz[i, n] else "nolut")
        out[k + (("GT" if (i, n) in gts else "noGT"),) if gts is not None else k] += 1
        if reason == "local" and k[2] == "arith":
            kind = "edge" if cedge[i, n] else ("pin" if lused[i, n] else "none")
            out[("detail", stage, kind, "fb" if fb[i, n] else "nofb", "chain_cont" if cont[i, n] else "chain_end") + ((("GT" if (i, n) in gts else "noGT"),) if gts is not None else ())] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="full")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--image", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "claim_filters.log"), "w")])
    cx = G.Ctx()
    tot = collections.Counter()
    if a.image:
        import cycloneiv_clean_image as IMG
        img = os.environ["PLURIBUS_DJI_IMAGE"]
        rbf, _, _ = IMG.container(open(img, "rb").read())
        open(IMG.PLANE, "wb").write(rbf)
        try:
            tot = classes(cx, T.plane_bits(IMG.PLANE))
        finally:
            os.remove(IMG.PLANE)
    else:
        ds = [d for d in G.tier_designs(a.tier) if os.path.basename(d).startswith(a.prefix)]
        for d in (ds[:a.limit] if a.limit else ds):
            _, _, ffs = G.parse_vo(os.path.join(d, "postfit.vo"))
            gts = {(cx.lut.lab(x, y), n) for (x, y, n) in ffs.values()}
            tot.update(classes(cx, T.plane_bits(os.path.join(d, "bitstream.rbf")), gts))
    for k, v in sorted(tot.items()):
        log.info("%7d  %s", v, k)


if __name__ == "__main__":
    main()
