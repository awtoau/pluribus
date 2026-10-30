#!/usr/bin/env python3.15t
"""Which pad feeds which PLL on the third-party image (env PLURIBUS_DJI_IMAGE), counts and pad names only (#176, #165).

  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_image_pll_pads.py [--pins 672]
For every enabled PLL: the programmed edge(s) into its PLL_CLKIN records (source type, index), walked upstream through programmed edges to the first pad
(IO_RAW_DATAIN / IO_DATAIN -> Row/Column I/O ball, CLK_BUFFER -> Dedicated Clock ball).  Log tmp/logs/image_pll_pads.log.
"""
import argparse
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_gate as G  # noqa: E402
import cycloneiv_clean_image as IMG  # noqa: E402
from lifters.cycloneiv_clean import emit as E, names, pll, tracer as T  # noqa: E402

log = logging.getLogger("image_pll_pads")
PADS = ("IO_RAW_DATAIN", "IO_DATAIN", "CLK_BUFFER")      # source: emit.PAD_SOURCES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pins", type=int, default=672)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "image_pll_pads.log"), "w")])
    rbf, _, _ = IMG.container(open(os.environ["PLURIBUS_DJI_IMAGE"], "rb").read())
    open(IMG.PLANE, "wb").write(rbf)
    try:
        cx = G.Ctx()
        bits = T.plane_bits(IMG.PLANE)
        edges = cx.ext.apply(bits, cx.st.fire(bits, workers=4))[G.HEADLINE]
        en = cx.ext.pllw.enabled(bits)
        pads = E.Ctx._pads(None, a.pins)
    finally:
        os.remove(IMG.PLANE)
    st = cx.st
    parent = {}
    for e in edges.tolist():
        parent.setdefault(int(st.edst[e]), []).append(int(st.esrc[e]))
    tiles = pll.pll_tiles()
    e_clk = names.enum_of("PLL_CLKIN")
    log.info("enabled PLLs: %s", sorted(en))
    for icd, (_, _, (x, y)) in sorted(tiles.items()):
        if icd not in en:
            continue
        for d in np.flatnonzero((cx.enum == e_clk) & (cx.rt.x == x) & (cx.rt.y == y)).tolist():
            hops, cur = [], d
            for _ in range(8):
                ps = parent.get(cur, [])
                if not ps:
                    break
                cur = ps[0]
                t = cx.tn(cur)
                hops.append(t)
                if t in PADS:
                    z = int(cx.rt.element(cur)[3])
                    p = pads.get(("CLK" if t == "CLK_BUFFER" else "IO", int(cx.rt.x[cur]), int(cx.rt.y[cur]), z))
                    hops.append("ball " + (p[1] if p else "unmapped"))
                    break
            log.info("PLL_%d PLL_CLKIN index %d: %s", icd, int(cx.rt.element(d)[4]), " <- ".join(hops) if hops else "no programmed driver")


if __name__ == "__main__":
    main()
