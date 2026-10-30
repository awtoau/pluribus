#!/usr/bin/env python3.15t
"""M9K write/read-enable control groups of the third-party EP4CGX150 image (#165): raw bit values of RAM_WRITE_ENABLE_INVERT / RAM_WE_FAST_MUX /
RAM_READ_ENABLE_INVERT / RAM_RE_FAST_MUX for the AF3-engine tiles and population counts over all tiles with a routed output.  Counts only.
  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_m9k_we_ctl.py [--tiles 7_85,7_86]     log tmp/logs/cycloneiv_clean_m9k_we_ctl.log
"""
import argparse, collections, logging, os, sys
import numpy as np
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "scripts"))
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_m9k_we_ctl.log")
log = logging.getLogger("m9k_we_ctl")
GROUPS = ("RAM_WRITE_ENABLE_INVERT", "RAM_WE_FAST_MUX", "RAM_READ_ENABLE_INVERT", "RAM_RE_FAST_MUX", "RAM_CE_INVERT", "RAM_CLOCK_INVERT")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--tiles", default="7_85,7_86"); a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    pf = os.path.join(REPO, "tmp", "inventory_image.path")          # untracked path file, fallback when the env var is unset
    path = os.environ.get("PLURIBUS_DJI_IMAGE") or (open(pf).read().strip() if os.path.exists(pf) else None)
    if not path or not os.path.exists(path): raise SystemExit("PLURIBUS_DJI_IMAGE not set or missing")
    import cycloneiv_decompress as cd
    from lifters.cycloneiv_clean import emit, m9k, m9k_usage
    plane = os.path.join(REPO, "tmp", "m9k_we_ctl_plane.rbf")
    open(plane, "wb").write(cd.decompress(open(path, "rb").read(), {}))
    try:
        cx = emit.Ctx(); b = emit.Builder(cx, plane, "image", 2); nl = b.run()
        mk = cx.m9kctl.decode(b.bits)
        u = m9k_usage.usage(cx, b.bits, b.edges, mk)
    finally:
        os.remove(plane)
    ctl = mk["ctl"]
    for t in a.tiles.split(","):
        x, y = map(int, t.split("_")); i = m9k.instance(x, y)
        log.info("[V] tile %s (instance %d): %s", t, i, {f'{g}#{k}': [int(v) for v in ctl[(g, k)][i]] for (g, k) in ctl if g in GROUPS})
        log.info("[V] tile %s pia lines wired (gi: lc): %s", t, {g: int(mk["pia_all"][i, g]) for g in range(12) if mk["pia_all"][i, g] >= 0})
    sel = u["outputs"]
    k0, k1 = ctl[("RAM_WRITE_ENABLE_INVERT", 0)][sel][:, 0], ctl[("RAM_WRITE_ENABLE_INVERT", 1)][sel][:, 0]
    log.info("[V] RAM_WRITE_ENABLE_INVERT (gi0, gi1) pairs over the population: %s", dict(collections.Counter(zip(k0.tolist(), k1.tolist()))))
    ins = [(int(x), int(y)) for x, y in ((m["x"], m["y"]) for m in nl.m9k) if m9k.instance(x, y) in set(np.where(sel)[0].tolist()) and int(ctl[("RAM_WRITE_ENABLE_INVERT", 1)][m9k.instance(x, y)][0]) == 0]
    log.info("[V] tiles with RAM_WRITE_ENABLE_INVERT gi1 = 0: %s", ins)
    for g in GROUPS:
        for (gg, k), arr in ctl.items():
            if gg != g: continue
            v = arr[sel]
            log.info("[V] population %d tiles, %s gi %s: set-bit histogram %s", int(sel.sum()), g, k, dict(collections.Counter(map(tuple, v.tolist()))))
if __name__ == "__main__": main()
