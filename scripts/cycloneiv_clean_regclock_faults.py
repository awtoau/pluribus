#!/usr/bin/env python3.15t
"""Classify the register_clock faults of the clean gate by cause (#165).

  python3.15t scripts/cycloneiv_clean_regclock_faults.py [--tier fast] [--workers 2]
Per GT register that is not `matched` in the gate: cause = claim withheld (reg_used) / LAB clock mux has no BLK_CLK_BUF line (and what it selects instead)
/ ...; and GT clock source type (element type of the net root).  Log tmp/logs/regclock_faults.log, json tmp/cycloneiv_clean/regclock_faults.json.
"""
import argparse
import collections
import json
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_gate as G  # noqa: E402
from lifters.cycloneiv_clean import tracer as T  # noqa: E402

log = logging.getLogger("regclock_faults")


def classify(cx, d):
    st = cx.st
    bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
    fired = cx.ext.apply(bits, st.fire(bits, workers=2))
    nets = T.parse_rcf(os.path.join(d, "routing.rcf"))
    allnames = sorted({e for n in nets for pc in n["edges"] for e in pc} | {r for n in nets for r in n["roots"]})
    idx = {n: i for i, n in enumerate(allnames)}
    rec, why = cx.res.resolve(allnames)
    gt_clk = {}
    for n in nets:
        rs = [int(rec[idx[r]]) for r in n["roots"] if rec[idx[r]] >= 0]
        rn = list(n["roots"])
        for last, cell, port, rp in n["dests"]:
            if port == "CLK":
                gt_clk[cell] = (rs, rn)
    ports, lcs, ffs = G.parse_vo(os.path.join(d, "postfit.vo"))
    qname = G.parse_ff_q(os.path.join(d, "postfit.vo"))
    ck = cx.ext.clocks
    ln = ck.lines(bits)
    sel = bits[ck.sel_cells].astype(np.int64)
    blk = ck.le_blk(bits)
    ffm = cx.ext.reg.ff(bits, fired[G.HEADLINE])
    out = collections.Counter()
    for name, (x, y, nn) in ffs.items():
        i = cx.lut.lab(x, y)
        gr = gt_clk.get(name) or gt_clk.get(qname.get(name))
        if i < 0:
            continue
        if not gr:
            out[("gt_clock_unresolved", name[:20])] += 1
            continue
        rs, rn = gr
        srct = "+".join(sorted({cx.tn(r) for r in rs})) or "?"
        if not ffm[i, nn]:
            if blk[i, nn] < 0:
                out[("claim_withheld+no_line", srct)] += 1
            else:
                out[("claim_withheld", srct)] += 1
        elif blk[i, nn] < 0:
            g = 0 if sel[i, nn] == 1 else 1
            m = ck.mux[g]
            v = bits[m.cells0[i]].astype(int).tolist()
            out[("no_clock_line", srct, "mux_gi%d_first_level=%s" % (g, "".join(map(str, v))))] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="fast")
    ap.add_argument("--only-faulty", help="json of gate run to restrict to designs with register_clock faults")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "regclock_faults.log"), "w")])
    gj = json.load(open(os.path.join(REPO, "tmp", "cycloneiv_clean", "gate_corpus_%s.json" % a.tier)))
    bad = [r["design"] for r in gj["rows"] if "error" not in r and (r["register_clock"]["missing"] or r["register_clock"]["extra"])]
    cx = G.Ctx()
    tot = collections.Counter()
    for dn in bad:
        c = classify(cx, os.path.join(REPO, "corpus", "cycloneiv", dn))
        tot.update(c)
        log.info("%s %s", dn, dict(c))
    log.info("TOTAL by (cause, gt clock source type, ...):")
    for k, v in tot.most_common():
        log.info("%6d  %s", v, k)


if __name__ == "__main__":
    main()
