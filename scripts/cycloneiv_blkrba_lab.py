#!/usr/bin/env python3.15t
"""TEST 1 of the blkrba hypothesis: do the (dx, dy) of the vendor blkrba bits give the in-LAB position
of the LUT INIT cells?  Decode: ddb_stingray_blkrba.ddb, 443 named bits (csv from
vendor-analysis/altera/inventory/s1/, gitignored; s1/scripts/blkrba.py).  Issue #165.

PREDICTION (written before the run)
- H1 (stated): a named bit at (dx, dy) sits at plane (frame, v) = (F0 + sf*dx, V0 + sv*dy), i.e. dx is
  the frame offset and dy the v offset; F0 = FX[X] and V0 = vy0 + 70*Y of the repo LAB anchor, signs free.
- H2 (alternative, from the table shape: dx spans 0..69 = the 70-v row pitch, dy spans 0..34 = the 35-frame
  column pitch): dx is v, dy is frame:  frame = FX[X] + (dy - dy0), v = vy0 + 70*Y + (dx0 - dx).
- Constants (dy0, dx0) are fitted from ONE cell (LE 0, RBLUT0); the other 255 labels x every LAB are the test.
- Oracle: the LUT-mask law (cycloneiv_le_locate.DK, geom.DN, odd-LE mirror), 100 % vs the post-fit .vo on the
  gx150 corpus (cycloneiv_lut_check.py).  Independent read-back: .vo lut_mask vs the bits read at the
  blkrba positions in the gx150 CRAM planes.
REFUTED if: H2 matches < 99 % of (LAB, LE, k) cells of the law, or the .vo read-back at blkrba positions is
below 99 % of mask bits.  H1 is refuted if its best sign/offset fit leaves cells off the law.

  python3.15t scripts/cycloneiv_blkrba_lab.py --csv <blkrba_stingray_abs.csv> [--designs 'gx150_*']
Log tmp/logs/cycloneiv_blkrba_lab.log
"""
import argparse
import collections
import csv
import itertools
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_le_locate as ll  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_blkrba_lab")
DEFAULT_CSV = REPO / "vendor-analysis/altera/inventory/s1/blkrba_stingray_abs.csv"
LUT = re.compile(r"^L:(\d+):RBLUT(\d+)$")


def load_csv(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return {r["name"]: (int(r["x_cum"]), int(r["y_cum"])) for r in rows}


def lut_table(names):
    t = {}
    for n, xy in names.items():
        m = LUT.match(n)
        if m:
            t[(int(m.group(1)), int(m.group(2)))] = xy
    assert len(t) == 256, len(t)
    return t


def law_cells(geom, tiles):
    """oracle (frame, v) arrays [tile, le, k] from the LUT-mask law."""
    n = len(tiles)
    F = np.zeros((n, 16, 16), np.int64)
    V = np.zeros((n, 16, 16), np.int64)
    for i, (x, y) in enumerate(tiles):
        f0, v0 = geom.anchor(x, y)
        for le in range(16):
            s = -1 if le % 2 else 1
            for k, (df, dv) in enumerate(ll.DK):
                F[i, le, k] = f0 + df
                V[i, le, k] = v0 + geom.DN[le] + s * dv
    return F, V


def model_cells(tab, geom, tiles, hyp, c):
    """hyp 'H2': frame = FX + dy - c[0], v = V0 + c[1] - dx.  hyp 'H1(sf,sv)': frame = FX + sf*(dx) + c0, v = V0 + sv*dy + c1."""
    n = len(tiles)
    F = np.zeros((n, 16, 16), np.int64)
    V = np.zeros((n, 16, 16), np.int64)
    anc = np.array([geom.anchor(x, y) for (x, y) in tiles])
    for (le, k), (dx, dy) in tab.items():
        if hyp == "H2":
            F[:, le, k] = anc[:, 0] + dy - c[0]
            V[:, le, k] = anc[:, 1] + c[1] - dx
        else:
            sf, sv = hyp
            F[:, le, k] = anc[:, 0] + sf * dx + c[0]
            V[:, le, k] = anc[:, 1] + sv * dy + c[1]
    return F, V


def fit_const(tab, geom, hyp):
    """Fit the two constants from LE 0 / k0 on a reference LAB (the only fitted cell)."""
    x, y = next((x, y) for x in sorted(geom.FX) if geom.col_kind(x) == "LAB" for y in (1,))
    f0, v0 = geom.anchor(x, y)
    dx, dy = tab[(0, 0)]
    if hyp == "H2":
        return (dy, dx)          # frame = FX + dy - dy0 -> dy0 = dy(k0); v = V0 + dx0 - dx -> dx0 = dx(k0)
    sf, sv = hyp
    return (-sf * dx, -sv * dy)


def compare(tab, geom, tiles, Fo, Vo, hyp):
    c = fit_const(tab, geom, hyp)
    Fm, Vm = model_cells(tab, geom, tiles, hyp, c)
    ok = (Fm == Fo) & (Vm == Vo)
    return ok, c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--designs", default="gx150_*")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-readback", action="store_true")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_blkrba_lab.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = load_csv(a.csv)
    tab = lut_table(names)
    geom = cg.load("ep4cgx150")
    labs = json.loads((REPO / "lifters/data/cycloneiv_ep4cgx150_labs.json").read_text())["labs"]
    tiles = sorted({(int(x), int(y)) for x, y in labs if geom.is_lab(int(x), int(y))})
    log.info("blkrba named bits %d, LUT bits %d; LAB tiles (legal fitter LABs that are LAB in geom) %d of %d",
             len(names), len(tab), len(tiles), len(labs))
    Fo, Vo = law_cells(geom, tiles)

    # -- TEST 1a: law vs blkrba, all LABs ------------------------------------------------------
    for hyp in ["H2"] + [h for h in itertools.product((1, -1), (1, -1))]:
        ok, c = compare(tab, geom, tiles, Fo, Vo, hyp)
        log.info("TEST1a %-9s consts %s: cells matched %d / %d = %.4f%%", str(hyp), c, ok.sum(), ok.size,
                 100 * ok.mean())
    ok, c = compare(tab, geom, tiles, Fo, Vo, "H2")
    per_lek = ok.sum(0)                                   # [le, k]
    bad_lek = [(le, k, int(per_lek[le, k])) for le in range(16) for k in range(16) if per_lek[le, k] != len(tiles)]
    per_tile = ok.reshape(len(tiles), -1).sum(1)
    bad_tiles = [(tiles[i], int(per_tile[i])) for i in range(len(tiles)) if per_tile[i] != 256]
    log.info("TEST1a H2: (LE,k) labels not exact in every LAB: %d; LABs with any off cell: %d", len(bad_lek), len(bad_tiles))
    if bad_lek:
        log.info("  off labels (le,k,labs_ok): %s", bad_lek[:20])
    if bad_tiles:
        log.info("  off LABs (tile, cells_ok): %s", bad_tiles[:20])
    # per-LE cell SETS (ignoring labels), tile 0
    setok = 0
    for le in range(16):
        so = {(int(Fo[0, le, k]), int(Vo[0, le, k])) for k in range(16)}
        Fm, Vm = model_cells(tab, geom, tiles[:1], "H2", c)
        sm = {(int(Fm[0, le, k]), int(Vm[0, le, k])) for k in range(16)}
        setok += so == sm
    log.info("TEST1a per-LE cell sets equal (LAB %s): %d / 16", tiles[0], setok)

    # -- TEST 1b: read-back vs .vo lut_mask, gx150 corpus ---------------------------------------
    if a.no_readback:
        return 0
    LOC = re.compile(r"^LCCOMB_X(\d+)_Y(\d+)_N(\d+)$")
    anc = cg.load("ep4cgx150")
    perm = [(le, k) for le in range(16) for k in range(16)]

    def one(name):
        d = cc.load(name)
        plane = d["plane"]
        c = collections.Counter()
        per = collections.Counter()
        for at in d["vo"].atoms.values():
            if at["type"] != "cycloneive_lcell_comb":
                continue
            mm = LOC.match(at.get("location") or "")
            if not mm:
                continue
            x, y, n = map(int, mm.groups())
            if x not in anc.FX or anc.col_kind(x) != "LAB":
                continue
            want = int(at["params"]["lut_mask"].split("'h")[1], 16)
            le = n // 2
            f0, v0 = anc.anchor(x, y)
            got = 0
            for k in range(16):
                dx, dy = tab[(le, k)]
                if plane[f0 + dy - c_fit[0], v0 + c_fit[1] - dx]:
                    got |= 1 << k
            diff = bin(got ^ want).count("1")
            c["bits_ok"] += 16 - diff
            c["bits_bad"] += diff
            c["cells"] += 1
            c["cells_exact"] += diff == 0
        return name, c

    c_fit = fit_const(tab, geom, "H2")
    ds = cc.designs(a.designs)
    tot = collections.Counter()
    with ThreadPoolExecutor(a.workers) as ex:
        for name, c in ex.map(one, ds):
            tot.update(c)
    m, w = tot["bits_ok"], tot["bits_bad"]
    log.info("TEST1b %d designs: LUT cells %d (exact %d); mask bits at blkrba positions vs .vo: matched %d / (matched + wrong %d) = %.4f%%",
             len(ds), tot["cells"], tot["cells_exact"], m, w, 100 * m / max(m + w, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
