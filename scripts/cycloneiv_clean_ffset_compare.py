#!/usr/bin/env python3.15t
"""Compare the emit's register set (Builder.ffp) with reg_used.ff (the gate / image figure), FF by FF, counts by class (#165).

  python3.15t scripts/cycloneiv_clean_ffset_compare.py --design gx150_rb_000
  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_ffset_compare.py --image
Prints: emit ffp, reg.ff, both, emit-only, gate-only; emit-only / gate-only split by sync bit, LUT INIT set, used buffer, clock source, arith.  Emit is built fresh from HEAD (no netlist cache).
Log tmp/logs/ffset_compare.log.
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
log = logging.getLogger("ffset_compare")


def compare(ctx, rbf):
    from lifters.cycloneiv_clean import emit
    B = emit.Builder(ctx, rbf, "cmp")
    nl = B.run()
    bits = ctx.T.plane_bits(rbf)
    rg = ctx.ext.reg
    gate = rg.ff(bits, B.edges)
    em = np.asarray(B.ffp, bool)
    sy = (bits[rg.sync[0]] == 1) & (bits[rg.sync[1]] == 1)
    nz = ctx.lut.cells(bits).sum(axis=2) > 0
    ub = rg.used(B.edges)
    ck = rg.clock_ok(bits)
    carry = ctx.lut.carry_in(bits)
    out = collections.Counter(emit=int(em.sum()), gate=int(gate.sum()), both=int((em & gate).sum()), nl_ffs=len(nl.ffs) if hasattr(nl, "ffs") else -1)
    for name, m in (("emit_only", em & ~gate), ("gate_only", gate & ~em)):
        for i, n in np.argwhere(m).tolist():
            out[(name, "sync" if sy[i, n] else "nosync", "lut" if nz[i, n] else "nolut", "buf" + "".join(str(int(x)) for x in ub[i, n]),
                 "clk" if ck[i, n] else "noclk", "arith" if carry[i, n] else "plain")] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--design")
    ap.add_argument("--image", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "ffset_compare.log"), "w")])
    from lifters.cycloneiv_clean import emit
    ctx = emit.Ctx()
    if a.image:
        import cycloneiv_decompress as cd
        plane = os.path.join(REPO, "tmp", "cycloneiv_clean", "ffset_plane.rbf")
        open(plane, "wb").write(cd.decompress(open(os.environ["PLURIBUS_DJI_IMAGE"], "rb").read(), {}))
        try:
            res = compare(ctx, plane)
        finally:
            os.remove(plane)
    else:
        res = compare(ctx, os.path.join(REPO, "corpus", "cycloneiv", a.design, "bitstream.rbf"))
    for k, v in sorted(res.items(), key=str):
        log.info("%8d  %s", v, k)


if __name__ == "__main__":
    main()
