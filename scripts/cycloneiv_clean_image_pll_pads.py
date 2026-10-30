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
        bits = bits.copy()
    finally:
        os.remove(IMG.PLANE)
    st = cx.st
    fired_set = set(edges.tolist())
    parent = {}
    for e in edges.tolist():
        parent.setdefault(int(st.edst[e]), []).append(int(st.esrc[e]))
    tiles = pll.pll_tiles()
    e_clk = names.enum_of("PLL_CLKIN")
    log.info("enabled PLLs: %s", sorted(en))
    def desc(r):
        t, x, y, z, i = cx.tn(r), *cx.rt.element(r)[1:]
        return f"{t}@X{x}Y{y}S{z}I{i}"

    def walk(r, path, depth, found):
        """every programmed-parent chain from `r` up to a pad (all parents, not the first)."""
        if depth > 14:
            return
        t = cx.tn(r)
        if t in PADS:
            p = pads.get(("CLK" if t == "CLK_BUFFER" else "IO", int(cx.rt.x[r]), int(cx.rt.y[r]), int(cx.rt.element(r)[3])))
            found.append((path + [desc(r)], p[1] if p else "unmapped"))
            return
        for q in parent.get(r, []):
            walk(q, path + [desc(r)], depth + 1, found)

    for icd, (_, _, (x, y)) in sorted(tiles.items()):
        if icd not in en:
            continue
        for d in np.flatnonzero((cx.enum == e_clk) & (cx.rt.x == x) & (cx.rt.y == y)).tolist():
            ps = parent.get(d, [])
            log.info("PLL_%d PLL_CLKIN index %d: %d programmed parents %s", icd, int(cx.rt.element(d)[4]), len(ps), [desc(q) for q in ps])
            for q in ps:                                  # select bits of the parent's own group: cell values of every graph parent of q
                es = np.flatnonzero(st.edst[:st.n_edges] == q).tolist()
                xc = st.xcell[st.xrec == q]
                log.info("   %s graph parents %d, exclusion cells %d set %d; parent cells: %s", desc(q), len(es), len(xc), int(bits[xc].sum()),
                         [(desc(int(st.esrc[e])), int(bits[st.cell[st.estart[e]]]), int(e in fired_set)) for e in es])
            found = []
            walk(d, [], 0, found)
            log.info("   pad chains: %d; balls %s", len(found), sorted({b for _, b in found}))
            for path, b in found[:6]:
                log.info("   ball %s via %s", b, " <- ".join(path))


if __name__ == "__main__":
    main()
