#!/usr/bin/env python3
"""Set bits of the third-party GX150 image that no vendor claim covers, grouped by region (#165, #169).

  PLURIBUS_DJI_IMAGE=<path> python3.15t scripts/cycloneiv_clean_residue_regions.py   # log tmp/logs/residue_regions.log, cells tmp/cycloneiv_clean/residue_cells.npz

- Claims = cycloneiv_clean_residue claim set (unclaimed map + DEFAULT_BIT_CALC) + option-register header cells (scored by options.py, not CRAM).
- Region key per residue cell: column kind, tile / band, frame span of the column, v band; counts only in the log (image path never printed).
"""
import collections
import glob
import logging
import os
import sys

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_residue as R  # noqa: E402
import cycloneiv_clean_unclaimed_map as U  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
from lifters.cycloneiv_clean import plane as P  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "residue_regions.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "residue_cells.npz")


def residue_cells(path, log=None):
    """-> dict of arrays for the image's set, unclaimed cells: s (frame), v (bit row), col, kind, tile, in_corpus, plus set count."""
    import json
    claimed, w, names = U.claimed_mask()
    claimed |= R.dbc_mask(w)
    g = json.load(open(R.GEOM))
    fx = np.array([g["FX"][str(i)] for i in range(len(g["FX"]))], np.int64)
    kinds = np.array([g["col_kind"][str(i)] for i in range(len(fx))] + ["pre"])
    N = P.N_BITS
    s = np.arange(N, dtype=np.int64) % P.FRAMES
    v = np.arange(N, dtype=np.int64) // P.FRAMES
    col = np.searchsorted(fx, s, side="right") - 1
    geo = cg.load(cg.die_of("EP4CGX150"))
    vmap = cc.vmap_for(P.RBF_FRAME_BYTES, tuple(geo.lane_bytes), tuple(map(tuple, geo.lane_swaps)))
    nv = len(vmap)
    tab = P.load_tables()
    flat = np.empty(N, np.int64)
    for a in range(0, N, R.CHUNK):
        flat[a:a + R.CHUNK] = R.plane_flat_ordered(np.arange(a, min(N, a + R.CHUNK), dtype=np.int64), nv, vmap, tab)
    plane = cc.cram_plane(open(path, "rb").read(), geo)
    img = np.zeros(6191 * nv, bool)
    img[plane.keys] = True
    ever = np.unpackbits(np.load(R.EVER))[:6191 * nv].astype(bool)
    m = img[flat] & ~claimed
    idx = np.nonzero(m)[0]
    return dict(addr=idx, s=s[idx], v=v[idx], col=col[idx], kind=kinds[col[idx]], tile=(v[idx] >= 23) & (v[idx] <= 6322),
                in_corpus=ever[flat[idx]], fx=fx[col[idx]], img_set=int(img.sum()), claimed_set=int((img[flat] & claimed).sum()))


# source: docs/cycloneiv-clean-options.md section 5: JTAG groups at frames 6134..6141 (rows 862..865), tdouser mux frames to 6145 in this image
JTAG_FRAMES = (6134, 6145)


def region(kind, tile, s, v):
    """Region label of one residue cell (column kind, tile / band, absolute frame, v)."""
    if kind == "pre" and tile:
        return "pre-column frames 0..20 (left periphery)"
    if tile and JTAG_FRAMES[0] <= s <= JTAG_FRAMES[1]:
        return "tile, JTAG block frames 6134..6145"
    if not tile and v in (0, 1, 2, 6341, 6342, 6343):
        return f"band edge rows, {'top' if v < 3 else 'bottom'} (v {'0..2' if v < 3 else '6341..6343'})"
    return "band other rows" if not tile else f"{kind} tile"


def cell_flat(addr):
    geo = cg.load(cg.die_of("EP4CGX150"))
    vmap = cc.vmap_for(P.RBF_FRAME_BYTES, tuple(geo.lane_bytes), tuple(map(tuple, geo.lane_swaps)))
    return R.plane_flat_ordered(addr, len(vmap), vmap, P.load_tables()), len(vmap)


def gate_designs():
    names = [ln.split("\t")[0] for ln in open(os.path.join(REPO, "reference", "gate_fast.tsv")).read().splitlines()[1:]]
    return [str(cc.CORPUS / n / "bitstream.rbf") for n in names if (cc.CORPUS / n / "bitstream.rbf").exists()
            and cc.device_of(n).startswith("EP4CGX150")]


def set_counts(flat, paths, nv):
    """-> (per cell: number of builds that set it, number of builds); a plane of another cell width is skipped."""
    geo = cg.load(cg.die_of("EP4CGX150"))
    c = np.zeros(len(flat), int)
    n = 0
    for p in paths:
        pl = cc.cram_plane(open(p, "rb").read(), geo)
        if pl.shape[1] == nv:
            c += np.isin(flat, pl.keys)
            n += 1
    return c, n


def main():
    path = os.environ.get("PLURIBUS_DJI_IMAGE")
    if not path:
        sys.exit("set PLURIBUS_DJI_IMAGE")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = logging.getLogger("rr")
    log.setLevel(logging.INFO)
    log.addHandler(logging.FileHandler(LOG, "w"))
    log.addHandler(logging.StreamHandler(sys.stdout))
    d = residue_cells(path)
    n = len(d["addr"])
    log.info("image plane cells set %d; claimed set %d; residue set %d (in corpus %d)", d["img_set"], d["claimed_set"], n, d["in_corpus"].sum())
    np.savez_compressed(OUT, **{k: d[k] for k in ("addr", "s", "v", "col", "kind", "tile", "in_corpus", "fx")})
    flat, nv = cell_flat(d["addr"])
    gate = set_counts(flat, gate_designs(), nv)
    pkg = {pk: set_counts(flat, sorted(glob.glob(os.path.join(REPO, "tmp", "pkgtest", f"*{pk}*", "bitstream.rbf"))), nv)
           for pk in ("CF23", "DF27", "DF31")}
    reg = np.array([region(k, t_, s_, v_) for k, t_, s_, v_ in zip(d["kind"], d["tile"], d["s"], d["v"])])
    for r in sorted(set(reg), key=lambda r: -(reg == r).sum()):
        m = reg == r
        g, n = gate
        pat = collections.Counter("".join("1" if c[0][i] == c[1] else "0" if c[0][i] == 0 else "m" for c in (pkg["CF23"], pkg["DF27"], pkg["DF31"]))
                                  for i in np.nonzero(m)[0])
        log.info("region %-34s %5d | gate builds (%d): set in all %d, in none %d, varies %d | package F484/F672/F896 set-in-all(1)/none(0)/mixed(m): %s",
                 r, m.sum(), n, (g[m] == n).sum(), (g[m] == 0).sum(), ((g[m] > 0) & (g[m] < n)).sum(), dict(pat.most_common(6)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
