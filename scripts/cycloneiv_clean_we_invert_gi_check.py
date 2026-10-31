#!/usr/bin/env python3.15t
"""RAM_WRITE_ENABLE_INVERT / RAM_WE_FAST_MUX gi <-> physical PIA write-enable line (gi 9 / gi 11) correspondence (#178):
cross-tabulate, over every M9K tile with exactly one write-enable PIA line wired (the 359 single/SDP-port tiles), which
PIA gi (9 or 11) is wired against which RAM_WRITE_ENABLE_INVERT / RAM_WE_FAST_MUX gi (0 or 1) differs from the die's
default pattern -- settles which invert-group gi index tracks which physical line.  Counts only.
  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_we_invert_gi_check.py     log tmp/logs/cycloneiv_clean_we_invert_gi_check.log
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_we_invert_gi_check.log")
log = logging.getLogger("we_invert_gi_check")


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    pf = os.path.join(REPO, "tmp", "inventory_image.path")
    path = os.environ.get("PLURIBUS_DJI_IMAGE") or (open(pf).read().strip() if os.path.exists(pf) else None)
    if not path or not os.path.exists(path):
        raise SystemExit("PLURIBUS_DJI_IMAGE not set or missing")
    import cycloneiv_decompress as cd
    from lifters.cycloneiv_clean import emit, m9k, m9k_usage
    plane = os.path.join(REPO, "tmp", "we_invert_gi_plane.rbf")
    open(plane, "wb").write(cd.decompress(open(path, "rb").read(), {}))
    try:
        cx = emit.Ctx(); b = emit.Builder(cx, plane, "image", 2); nl = b.run()
        mk = cx.m9kctl.decode(b.bits)
        u = m9k_usage.usage(cx, b.bits, b.edges, mk)
    finally:
        os.remove(plane)
    ctl = mk["ctl"]
    sel = u["outputs"]
    w9 = mk["pia_all"][:, 9] >= 0
    w11 = mk["pia_all"][:, 11] >= 0
    only9 = sel & w9 & ~w11
    only11 = sel & w11 & ~w9
    both = sel & w9 & w11
    log.info("[V] population: gi9-only %d, gi11-only %d, both %d, neither (of selected) %d",
             int(only9.sum()), int(only11.sum()), int(both.sum()), int((sel & ~w9 & ~w11).sum()))
    for g in (0, 1):
        inv = ctl[("RAM_WRITE_ENABLE_INVERT", g)][:, 0]
        fm = ctl[("RAM_WE_FAST_MUX", g)]
        log.info("[V] gi%d: RAM_WRITE_ENABLE_INVERT histogram over gi9-only tiles: %s", g, dict(collections.Counter(inv[only9].tolist())))
        log.info("[V] gi%d: RAM_WRITE_ENABLE_INVERT histogram over gi11-only tiles: %s", g, dict(collections.Counter(inv[only11].tolist())))
        log.info("[V] gi%d: RAM_WE_FAST_MUX histogram over gi9-only tiles: %s", g, dict(collections.Counter(map(tuple, fm[only9].tolist()))))
        log.info("[V] gi%d: RAM_WE_FAST_MUX histogram over gi11-only tiles: %s", g, dict(collections.Counter(map(tuple, fm[only11].tolist()))))
    log.info("[V] both-wired tile indices: %s", np.where(both)[0].tolist())
    for i in np.where(both)[0].tolist():
        ins = [(int(x), int(y)) for x, y in ((m["x"], m["y"]) for m in nl.m9k) if m9k.instance(x, y) == i]
        log.info("[V] instance %d tiles %s: WRITE_ENABLE_INVERT gi0=%s gi1=%s; WE_FAST_MUX gi0=%s gi1=%s", i, ins,
                  int(ctl[("RAM_WRITE_ENABLE_INVERT", 0)][i, 0]), int(ctl[("RAM_WRITE_ENABLE_INVERT", 1)][i, 0]),
                  ctl[("RAM_WE_FAST_MUX", 0)][i].tolist(), ctl[("RAM_WE_FAST_MUX", 1)][i].tolist())


if __name__ == "__main__":
    main()
