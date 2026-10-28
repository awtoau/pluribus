#!/usr/bin/env python3.15t
"""Die map with one EP4CGX150 image's KNOWN cells overlaid + the zero-vs-one encoding measurements (issue #141).

  python3.15t scripts/geo_image_overlay.py --image <image.bin|.rbf> [--stage all|attrib|encoding]
  python3.15t scripts/geo_image_overlay.py --repin     # page only, from the cached tmp/geo/image_overlay_data.json
Needs >= 20 GB MemAvailable (peak ~4 GB).  Reuses the inventory's class assignment (cycloneiv_bit_inventory
imported read-only; its claim logic is repeated here only to carry a tile OWNER per cell).
Outputs (tmp/geo/, not committed): image_tiles.csv, image_tiles.geojson, image_encoding.json, image_overlay.html.
Log tmp/logs/geo_image_overlay.log.  Method + approximations: docs/geo-image-overlay.md.
"""
import argparse
import base64
import collections
import csv
import glob
import hashlib
import json
import logging
import sys
import zlib
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
GEO = REPO / "tmp/geo"
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts"))
log = logging.getLogger("geo_image_overlay")

import os  # noqa: E402
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "databases/cycloneiv/gx150.db"))   # specimen evidence rows
import geo_pins  # noqa: E402
import cycloneiv_bit_inventory as bi  # noqa: E402  (read-only reuse: Inv, CLASSES, CID, forced_table, ...)

NV, LANE_V = bi.NV, bi.LANE_V
CLS = bi.CLASSES
CID = bi.CID
IDS = [c[0] for c in CLS]                     # index i -> class id string; class number = i + 1
NCLS = len(CLS) + 1                           # 0 = none
# tile accounting tiers (class number -> tier): 5b (CRC) is overhead, excluded from the known fraction
TIER = {}
for i, (cid, _n, _t) in enumerate(CLS):
    TIER[i + 1] = ("V" if cid == "1a" else "E" if cid in ("1b", "1c", "2a", "2b", "3")
                   else "O" if cid in ("5a", "5b") else "U")
YROWS = 92                                    # y = 0..91
VBAND_LO = 48                                 # tile row band of y = [70 y - 48, 70 y + 21] = [VY-68, VY+1]
KINDS = ["LAB", "M9K", "MUL", "IOL", "IOR", "IOROW"]


# ---------------------------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------------------------
def load_image(raw, g):
    import cycloneiv_corpus as cc
    import cycloneiv_decompress as cd
    plane = cc.cram_plane(raw, g)
    info = {}
    u = cd.decompress(raw, info)
    F, nper, ncram = info["frame"], info["periphery_frames"], info["cram_frames"]
    nfr = nper + ncram
    assert F * 8 == NV
    sm = np.zeros(nfr * NV, bool)
    sm[np.asarray(plane.keys, np.int64)] = True
    crc_set = 0
    for fr in range(nper, nfr):                 # CRC bytes are not in the plane; frame bit b -> v = b for b >= 6344
        b0 = cd.PREAMBLE + fr * F + F - 2
        bits = np.unpackbits(np.frombuffer(u[b0:b0 + 2], np.uint8), bitorder="little")
        sm[fr * NV + 6352 + np.flatnonzero(bits)] = True
        crc_set += int(bits.sum())
    hdr = u[cd.PREAMBLE:cd.PREAMBLE + F]
    hdr_set = int(np.unpackbits(np.frombuffer(hdr, np.uint8)).sum())
    return plane, sm, dict(nfr=nfr, nper=nper, F=F, hdr_set=hdr_set, crc_set=crc_set, plane_set=len(plane.keys))


# ---------------------------------------------------------------------------------------------
# classification with a tile owner per cell
# ---------------------------------------------------------------------------------------------
class Cells:
    def __init__(self, g, nfr, nper):
        self.g, self.nfr, self.nper = g, nfr, nper
        self.inv = bi.Inv(g, nfr, nper)           # colx per frame (FX-19 band start), cls array
        self.cls = self.inv.cls
        v = np.arange(NV)
        self.ydef = np.clip((v + VBAND_LO) // g.vpitch, 0, g.ymax).astype(np.int16)
        self.ocol = np.empty((nfr, NV), np.int16)
        self.ocol[:] = self.inv.colx.astype(np.int16)[:, None]
        self.orow = np.empty((nfr, NV), np.int16)
        self.orow[:] = self.ydef[None, :]
        self.orow[:nper] = -1
        self.ocol = self.ocol.reshape(-1)
        self.orow = self.orow.reshape(-1)
        self.dups = collections.Counter()

    def claim(self, flat, name, oc=None, orr=None):
        flat = np.asarray(flat, np.int64)
        ok = (flat >= 0) & (flat < len(self.cls))
        flat = flat[ok]
        if oc is not None:
            oc, orr = np.asarray(oc)[ok], np.asarray(orr)[ok]
        u, first = np.unique(flat, return_index=True)
        self.dups[name] += len(flat) - len(u)
        free = self.cls[u] == 0
        sel = u[free]
        self.cls[sel] = CID[name]
        if oc is not None:
            self.ocol[sel] = oc[first][free]
            self.orow[sel] = orr[first][free]
        return int(free.sum()), len(u)


def classify(g, plane, nfr, nper, dec):
    """cls (uint8, class number per cell), ocol/orow (owner tile per cell), fired mask."""
    from cycloneiv_le_locate import DK
    C = Cells(g, nfr, nper)
    tiles = bi.lab_tiles(g)
    nt = len(tiles)
    tcol, trow = tiles[:, 0], tiles[:, 1]
    f0, v0, sg = bi.le_grid(g, tiles)
    own_c, own_r = np.repeat(tcol, 16), np.repeat(trow, 16)
    lut = np.concatenate([((f0 + df) * NV + v0 + sg * dv).ravel() for df, dv in DK])
    C.claim(lut, "1a", np.tile(own_c, len(DK)), np.tile(own_r, len(DK)))
    C.claim(((f0 - 8) * NV + v0 - sg).ravel(), "1b", own_c, own_r)
    fx = np.array([g.FX[int(x)] for x in tcol], np.int64)
    vy = g.vy0 + g.vpitch * trow
    C.claim((fx - 6) * NV + vy - 30, "1c", tcol, trow)
    # 2: asm routing; owner column = column whose FX is the largest <= frame (asm band is FX..FX+17)
    gids, _grec, _blk = dec.active(plane)
    fg = np.zeros(len(dec.gsize), bool)
    fg[gids] = True
    pf, pvv, gid = np.asarray(dec.pf), np.asarray(dec.pv), np.asarray(dec.gid)
    asm_any = np.zeros(nfr * NV, bool)
    fired = np.zeros(nfr * NV, bool)
    for s in range(0, len(pf), 5_000_000):
        p, q = pf[s:s + 5_000_000].astype(np.int64), pvv[s:s + 5_000_000].astype(np.int64)
        ok = (p >= 0) & (p < nfr) & (q >= 0) & (q < NV)
        flat = p[ok] * NV + q[ok]
        asm_any[flat] = True
        fired[flat[fg[gid[s:s + 5_000_000]][ok]]] = True
    fxs = np.array(sorted(g.FX.values()), np.int64)
    xs_by_fx = np.array(sorted(g.FX, key=lambda x: g.FX[x]), np.int64)
    for nm, m in (("2a", fired), ("2b", asm_any & ~fired)):
        flat = np.flatnonzero(m)
        fr = flat // NV
        col = xs_by_fx[np.clip(np.searchsorted(fxs, fr, "right") - 1, 0, len(fxs) - 1)]
        C.claim(flat, nm, col, C.orow[flat])
    del pf, pvv, gid
    # 3: specimens
    pats, rel = [], None
    for fp, (lx, ly) in zip(bi.FORCED, bi.FORCED_LAB):
        tab = bi.forced_table(fp)
        cur = {}
        for r in tab.values():
            cur[(r["src"], r["snk"], r["hop"][4])] = tuple(sorted((b // NV - g.FX[lx], b % NV - (g.vy0 + g.vpitch * ly)) for b in r["on"]))
        if rel is None:
            rel = cur
    universe = sorted({b for p in rel.values() for b in p})
    sc = np.concatenate([((fx + df) * NV + vy + dv) for df, dv in universe])
    C.claim(sc, "3", np.tile(tcol, len(universe)), np.tile(trow, len(universe)))
    log.info("specimen universe %d cells/LAB, frame offsets %d..%d", len(universe), min(d for d, _ in universe), max(d for d, _ in universe))
    # 4/5/6 by geometry (same rules as the inventory)
    inv = C.inv
    cls2 = C.cls.reshape(nfr, NV)
    kind = ["x"] * nfr
    for f in range(nfr):
        kind[f] = "per" if 1 <= f < nper else "hdr" if f == 0 else (g.kind[int(inv.colx[f])] if inv.colx[f] in g.kind else "IOL")
    kind = np.array(kind, object)
    ff = lambda k: np.flatnonzero(kind == k)
    cell = lambda fr, a, b: (fr[:, None] * NV + np.arange(a, b)[None, :]).ravel()
    C.claim(cell(ff("per"), 0, NV), "4a")
    C.claim(cell(ff("M9K"), 0, LANE_V), "4b")
    C.claim(cell(ff("MUL"), 0, LANE_V), "4c")
    C.claim(np.concatenate([cell(ff("IOL"), 0, LANE_V), cell(ff("IOR"), 0, LANE_V)]), "4d")
    labf = ff("LAB")
    vio = np.flatnonzero((inv.rowy == 0) | (inv.rowy == g.ymax))
    C.claim((labf[:, None] * NV + vio[None, :]).ravel(), "4e")
    C.claim(cell(np.array([0]), 0, NV), "5a")
    C.claim(cell(np.arange(nper, nfr), 6352, NV), "5b")
    C.claim(cell(np.arange(nper, nfr), LANE_V, 6352), "5c")
    C.cls[C.cls == 0] = CID["6"]
    C.ocol[:NV] = -1                                  # header frame: no tile
    C.orow[:NV] = -1
    C.ocol[:nper * NV] = -1                           # periphery frames: no tile
    log.info("claimed cells per class %s", {IDS[i - 1]: int(n) for i, n in enumerate(np.bincount(C.cls, minlength=NCLS)) if i})
    log.info("duplicate claims within a class (cell asked for by 2 tiles): %s", dict(C.dups))
    return C, tiles, fired, asm_any


# ---------------------------------------------------------------------------------------------
# part 1: per-tile table
# ---------------------------------------------------------------------------------------------
def tile_hist(C, sm, g):
    """H[x, y, cls] cells and Hs set cells (owner tile)."""
    nx = g.xmax + 1
    v = C.ocol >= 0
    tid = C.ocol[v].astype(np.int64) * YROWS + C.orow[v]
    cl = C.cls[v].astype(np.int64)
    H = np.bincount(tid * 16 + cl, minlength=nx * YROWS * 16).reshape(nx, YROWS, 16)
    Hs = np.bincount((tid * 16 + cl)[sm[v]], minlength=nx * YROWS * 16).reshape(nx, YROWS, 16)
    return H, Hs


def tier_sum(A, tier):
    """A[..., 16] -> sum over classes of the given tier"""
    idx = [c for c in range(1, NCLS) if TIER[c] == tier]
    return A[..., idx].sum(-1)


def tile_kind(g, x, y):
    k = g.kind[x]
    return "IOROW" if (y in (0, g.ymax) and k == "LAB") else k


def build_table(H, Hs, g):
    nx = g.xmax + 1
    verc, evic, unkc, ovc = (tier_sum(H, t) for t in "VEUO")
    sv, se, su, so = (tier_sum(Hs, t) for t in "VEUO")
    cells = H.sum(-1)
    sets = Hs.sum(-1)
    rows = []
    for x in range(nx):
        for y in range(YROWS):
            k = sv[x, y] + se[x, y]
            denom = sv[x, y] + se[x, y] + su[x, y]
            rows.append(dict(x=x, y=y, kind=tile_kind(g, x, y), cells=int(cells[x, y]), set=int(sets[x, y]),
                             set_ver=int(sv[x, y]), set_evi=int(se[x, y]), set_unk=int(su[x, y]), set_ovh=int(so[x, y]),
                             known_frac=(float(k / denom) if denom else None),
                             cap_ver=int(verc[x, y]), cap_evi=int(evic[x, y]),
                             cap_frac=float((verc[x, y] + evic[x, y]) / cells[x, y]) if cells[x, y] else 0.0,
                             cls_cells={IDS[c - 1]: int(H[x, y, c]) for c in range(1, NCLS) if H[x, y, c]},
                             cls_set={IDS[c - 1]: int(Hs[x, y, c]) for c in range(1, NCLS) if Hs[x, y, c]}))
    return rows


def write_tables(rows, nx):
    ids = IDS
    with open(GEO / "image_tiles.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["x", "y", "kind", "cells", "set", "set_verified", "set_evidence", "set_unknown", "set_overhead_crc",
                    "known_frac", "cap_verified", "cap_evidence", "cap_frac"] + [f"cells_{i}" for i in ids] + [f"set_{i}" for i in ids])
        for r in rows:
            w.writerow([r["x"], r["y"], r["kind"], r["cells"], r["set"], r["set_ver"], r["set_evi"], r["set_unk"], r["set_ovh"],
                        "" if r["known_frac"] is None else f"{r['known_frac']:.4f}", r["cap_ver"], r["cap_evi"], f"{r['cap_frac']:.4f}"]
                       + [r["cls_cells"].get(i, 0) for i in ids] + [r["cls_set"].get(i, 0) for i in ids])
    feats = [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[r["x"], r["y"]], [r["x"] + 1, r["y"]], [r["x"] + 1, r["y"] + 1], [r["x"], r["y"] + 1], [r["x"], r["y"]]]]},
              "properties": {"x": r["x"], "y": r["y"], "kind": r["kind"], "cells": r["cells"], "set": r["set"], "ver": r["set_ver"],
                             "evi": r["set_evi"], "unk": r["set_unk"], "known": None if r["known_frac"] is None else round(r["known_frac"], 3),
                             "cap": round(r["cap_frac"], 3)}} for r in rows]
    (GEO / "image_tiles.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))


def tile_rects(C, g, nper, nfr):
    """frame rectangle [fa, fb) per column = exact extent of the frames that hold cells owned by that column."""
    oc2 = C.ocol.reshape(nfr, NV)
    fa, fb = {}, {}
    for f in range(nper, nfr):
        for x in np.unique(oc2[f]).tolist():
            if x >= 0:
                fa.setdefault(x, f)
                fb[x] = f + 1
    return {x: (fa[x], fb[x]) for x in sorted(fa)}


def pack_bitmaps(C, sm, g, rows, nper, nfr):
    rects = tile_rects(C, g, nper, nfr)
    cmerged = C.cls.copy()
    cmerged[cmerged == CID["2a"]] = CID["2b"]
    cm2 = cmerged.reshape(nfr, NV)
    sm2 = sm.reshape(nfr, NV)
    oc2, or2 = C.ocol.reshape(nfr, NV), C.orow.reshape(nfr, NV)
    tm, tmpl_index, sbytes, outside = {}, [], [], 0
    tl = []
    for r in rows:
        x, y = r["x"], r["y"]
        fa, fb = rects[x]
        va = g.vpitch * y - VBAND_LO
        vlo, vhi = max(va, 0), min(va + g.vpitch, NV)
        w = fb - fa
        own = np.zeros((w, g.vpitch), bool)
        cm = np.zeros((w, g.vpitch), np.uint8)
        sb = np.zeros((w, g.vpitch), bool)
        if vhi > vlo:
            sl = (slice(fa, fb), slice(vlo, vhi))
            o = (oc2[sl] == x) & (or2[sl] == y)
            own[:, vlo - va:vhi - va] = o
            cm[:, vlo - va:vhi - va] = np.where(o, cm2[sl], 0)
            sb[:, vlo - va:vhi - va] = sm2[sl] & o
        outside += r["cells"] - int(own.sum())
        key = hashlib.blake2b(cm.tobytes(), digest_size=12).digest()
        if key not in tm:
            tm[key] = len(tm)
            tl.append(cm.tobytes())
        tmpl_index.append(tm[key])
        sbytes.append(np.packbits(sb.ravel()).tobytes())
        r["fa"], r["w"], r["tmpl"] = fa, w, tm[key]
    # owned cells that fall outside their tile rectangle (should be ~0)
    log.info("owned cells outside their tile rectangle (not drawn in the bitmap, still counted): %d; unique class templates %d", outside, len(tl))
    offs, p = [], 0
    for t in tl:
        offs.append([p, len(t)]); p += len(t)
    Cblob = zlib.compressobj(9, zlib.DEFLATED, -15)
    cb = Cblob.compress(b"".join(tl)) + Cblob.flush()
    Sraw = b"".join(sbytes)
    Sblob = zlib.compressobj(9, zlib.DEFLATED, -15)
    sb_ = Sblob.compress(Sraw) + Sblob.flush()
    log.info("bitmaps: class templates %d B raw -> %d B deflated; set bits %d B raw -> %d B deflated", p, len(cb), len(Sraw), len(sb_))
    return dict(C=base64.b64encode(cb).decode(), S=base64.b64encode(sb_).decode(), tp=offs)


# ---------------------------------------------------------------------------------------------
# part 3: encoding measurements
# ---------------------------------------------------------------------------------------------
def evidence_polarity():
    """Specimen 'on' (cell set in specimen, clear in base) vs 'off' (set in base, clear in specimen), all evidence files."""
    import db
    cur = db.connect_threadsafe().cursor()
    cur.execute("select source_ref, result from evidence where kind='specimen-pair'")
    res = {}
    for ref, result in cur.fetchall():
        r = json.loads(result) if isinstance(result, str) else result
        d = res.setdefault(Path(ref).name, dict(pairs=0, cells_0_to_1=0, cells_1_to_0=0))
        d["pairs"] += 1
        d["cells_0_to_1"] += int(r["n_spec"])
        d["cells_1_to_0"] += int(r["n_base"])
    return res


def routing_blocks(dec, plane):
    """Blocks = asm muxes.  How many are all-zero, one-hot (fired), partially set; groups whose predicted pattern is empty."""
    s = np.flatnonzero(plane.has(np.asarray(dec.pf), np.asarray(dec.pv)))
    uk = np.unique(np.asarray(dec.e_ukey)[s])
    bset = np.bincount(dec.ukey_block[uk], minlength=dec.nblocks)
    btot = np.bincount(dec.ukey_block, minlength=dec.nblocks)
    gids, _r, blk = dec.active(plane)
    fired_blocks = np.zeros(dec.nblocks, bool)
    fired_blocks[blk] = True
    placed = btot > 0
    gid = np.asarray(dec.gid)
    z = dec.npred == 0
    npred0 = int(z.sum())
    ze = np.bincount(np.asarray(dec.block)[z], minlength=dec.nblocks)       # empty-pattern groups per block
    allz = (bset == 0) & placed
    split = dict(placed_blocks_with_empty_group=int((placed & (ze > 0)).sum()), of_which_all_zero=int((allz & (ze > 0)).sum()),
                 placed_blocks_without_empty_group=int((placed & (ze == 0)).sum()), without_all_zero=int((allz & (ze == 0)).sum()),
                 blocks_with_exactly_one_empty_group=int((ze == 1).sum()), blocks_with_2plus_empty_groups=int((ze > 1).sum()))
    return dict(**split, blocks=int(dec.nblocks), blocks_with_placed_cells=int(placed.sum()),
                blocks_all_zero=int(((bset == 0) & placed).sum()),
                blocks_some_set=int(((bset > 0) & placed).sum()),
                blocks_fired_one_group=int(fired_blocks.sum()),
                blocks_set_not_fired=int(((bset > 0) & placed & ~fired_blocks).sum()),
                blocks_all_cells_set=int(((bset == btot) & placed).sum()),
                groups=int(len(dec.gsize)), groups_with_empty_predicted_pattern=npred0,
                fired_groups=int(len(gids)),
                set_cells_in_fired_blocks=int(bset[fired_blocks].sum()),
                set_cells_in_unfired_blocks=int(bset[~fired_blocks].sum()))


def le_stats(g, sm, tiles):
    from cycloneiv_le_locate import DK
    f0, v0, sg = bi.le_grid(g, tiles)
    bits = np.stack([sm[(f0 + df) * NV + v0 + sg * dv] for df, dv in DK], -1)           # (tile, LE, 16)
    init = (bits.astype(np.uint32) << np.arange(16, dtype=np.uint32)).sum(-1)
    used = sm[(f0 - 8) * NV + v0 - sg]
    clk = sm[(np.array([g.FX[int(x)] for x in tiles[:, 0]], np.int64) - 6) * NV + g.vy0 + g.vpitch * tiles[:, 1] - 30]
    def dist(m):
        a = init[m]
        pc = bits[m].sum(-1)
        top = collections.Counter(a.tolist()).most_common(6)
        return dict(n=int(m.sum()), init_zero=int((a == 0).sum()), init_ffff=int((a == 0xFFFF).sum()),
                    init_other=int(((a != 0) & (a != 0xFFFF)).sum()), popcount_mean=float(pc.mean()) if len(pc) else None,
                    top_inits=[[f"{k:04x}", c] for k, c in top])
    return dict(les=int(used.size), used_bit_set=int(used.sum()), unused=dist(~used), used=dist(used),
                lab_clock_bit_set=int(clk.sum()), labs=int(len(tiles))), used, init


def rel_freq(C, sm, g, mask_tile):
    """Set frequency per tile-relative cell (frame offset FX-19..FX+17 x v row 0..69) over LAB core tiles (y 1..90)
    where mask_tile[x, y]."""
    keys = np.flatnonzero(sm)
    oc, orr = C.ocol[keys].astype(np.int64), C.orow[keys].astype(np.int64)
    fx = np.array([g.FX.get(x, -10**6) for x in range(g.xmax + 1)], np.int64)
    islab = np.array([g.kind[x] == "LAB" for x in range(g.xmax + 1)])
    ok = (oc >= 0) & islab[np.clip(oc, 0, None)] & (orr >= 1) & (orr <= g.ymax - 1)
    ok &= mask_tile[np.clip(oc, 0, None), np.clip(orr, 0, None)]
    k = keys[ok]
    rf = k // NV - fx[oc[ok]] + 19
    rv = k % NV - (g.vpitch * orr[ok] - VBAND_LO)
    good = (rf >= 0) & (rf < 37) & (rv >= 0) & (rv < g.vpitch)
    cnt = np.zeros((37, g.vpitch), np.int64)
    np.add.at(cnt, (rf[good], rv[good]), 1)
    return cnt, int(good.sum())


def encoding(C, sm, plane, dec, g, tiles, meta, H, Hs, fired):
    out = {}
    nfr, nper = meta["nfr"], meta["nper"]
    tot_cells = nfr * NV
    out["image"] = dict(plane_set=meta["plane_set"], header_set=meta["hdr_set"], crc_set=meta["crc_set"],
                        set_bits_incl_header_crc_prepost=meta["plane_set"] + meta["hdr_set"] + meta["crc_set"] + 728,
                        frames=nfr, periphery_frames=nper - 1, bits_per_frame=NV)
    # (a) set fraction overall and per class (2a/2b separate)
    cnt = np.bincount(C.cls, minlength=NCLS)
    st = np.bincount(C.cls[sm], minlength=NCLS)
    rows = []
    for i, (cid, name, tier) in enumerate(CLS, 1):
        t, s = int(cnt[i]), int(st[i])
        if cid == "5a":
            s = meta["hdr_set"]
        rows.append(dict(id=cid, name=name, tier=tier, cells=t, set=s, set_frac=s / t if t else None))
    rows.append(dict(id="5d", name="preamble + postamble", tier="constant", cells=728, set=728, set_frac=1.0))
    out["per_class"] = rows
    plane_cells = (nfr - 1) * NV
    out["overall"] = dict(plane_cells=plane_cells, plane_set=int(sm.sum()), plane_set_frac=float(sm.sum() / plane_cells),
                          die_bits=39425016, die_set=meta["plane_set"] + meta["hdr_set"] + meta["crc_set"] + 728)
    out["overall"]["die_set_frac"] = out["overall"]["die_set"] / 39425016
    # per frame set fraction, > 50%
    fr_set = sm.reshape(nfr, NV).sum(1)
    hi = [(int(f), float(fr_set[f] / NV)) for f in range(1, nfr) if fr_set[f] > NV / 2]
    out["frames_over_half"] = dict(n=len(hi), list=hi[:40], max_frac_cram=float(fr_set[nper:].max() / NV),
                                   median_frac_cram=float(np.median(fr_set[nper:]) / NV))
    vrow = sm.reshape(nfr, NV)[nper:].sum(0)
    out["vrows_over_half"] = [int(v) for v in np.flatnonzero(vrow > (nfr - nper) / 2)]
    out["vrow_max_frac"] = float(vrow.max() / (nfr - nper))
    # (b) LEs / idle LABs
    les, used, init = le_stats(g, sm, tiles)
    out["le"] = les
    tcol, trow = tiles[:, 0], tiles[:, 1]
    c = lambda name: Hs[:, :, CID[name]]
    idle = (c("1b") == 0) & (c("1c") == 0) & (c("2a") == 0)           # nothing that decodes as used
    labtile = np.zeros_like(idle)
    labtile[tcol, trow] = True
    idle &= labtile
    dead = (Hs.sum(-1) == 0) & labtile
    out["idle_labs"] = dict(lab_tiles=int(labtile.sum()), idle_by_decode=int(idle.sum()), zero_set_bits_total=int(dead.sum()))
    if idle.any():
        ic, isc = H[idle].sum(0), Hs[idle].sum(0)
        out["idle_labs"]["per_class"] = [dict(id=IDS[i - 1], cells=int(ic[i]), set=int(isc[i]), set_frac=float(isc[i] / ic[i])) for i in range(1, NCLS) if ic[i]]
        out["idle_labs"]["set_frac_all"] = float(isc.sum() / ic.sum())
    nonidle = labtile & ~idle
    out["busy_labs_set_frac_all"] = float(Hs[nonidle].sum() / H[nonidle].sum())
    # tile-relative cells set in > 50 % of tiles (LAB core rows y 1..90)
    rowok = (np.arange(YROWS)[None, :] >= 1) & (np.arange(YROWS)[None, :] <= g.ymax - 1)
    allm = labtile & rowok
    cnt_all, _ = rel_freq(C, sm, g, allm)
    cnt_idle, _ = rel_freq(C, sm, g, idle & rowok)
    n_all, n_idle = int(allm.sum()), int((idle & rowok).sum())
    fa_, fi_ = cnt_all / n_all, cnt_idle / max(n_idle, 1)
    fb_ = (cnt_all - cnt_idle) / max(n_all - n_idle, 1)
    sel = np.argwhere((fa_ > 0.5) | (fi_ > 0.5))
    cells = []
    for rf, rv in sel.tolist():
        f = g.FX[20] - 19 + rf                           # class lookup in a mid-die LAB column (class layout is regular)
        v = g.vpitch * 40 - VBAND_LO + rv
        cells.append(dict(frame_off=rf - 19, v_row=rv, freq_all=round(float(fa_[rf, rv]), 3), freq_idle=round(float(fi_[rf, rv]), 3),
                          freq_busy=round(float(fb_[rf, rv]), 3), cls=IDS[C.cls[f * NV + v] - 1]))
    out["lab_cells_over_half"] = dict(tiles_all=n_all, tiles_idle=n_idle, cells=cells,
                                      idle_set_bits_in_these_cells=int(sum(cnt_idle[c["frame_off"] + 19, c["v_row"]] for c in cells if c["freq_idle"] > .5)),
                                      idle_set_bits_total=int(cnt_idle.sum()))
    # cells set in every one of the 6 GX150 images are added in other_images()
    # (d) routing blocks
    out["routing"] = routing_blocks(dec, plane)
    out["evidence_polarity"] = evidence_polarity()
    # (e) M9K and multiplier tiles
    nx = g.xmax + 1
    rects = tile_rects(C, g, nper, nfr)
    keys = np.flatnonzero(sm)
    oc, orr = C.ocol[keys].astype(np.int64), C.orow[keys].astype(np.int64)
    for kname in ("M9K", "MUL"):
        xs = [x for x in range(nx) if g.kind[x] == kname]
        tot = np.array([[Hs[x, y].sum() for y in range(1, g.ymax)] for x in xs])      # y 1..90
        cells = np.array([[H[x, y].sum() for y in range(1, g.ymax)] for x in xs])
        flat = tot.ravel()
        q25 = np.quantile(flat, .25)
        w = max(rects[x][1] - rects[x][0] for x in xs)
        cnt = np.zeros((w, g.vpitch), np.int64)
        cnt_lo = np.zeros_like(cnt)
        for xi, x in enumerate(xs):
            m = (oc == x) & (orr >= 1) & (orr <= g.ymax - 1)
            kk, rr = keys[m], orr[m]
            np.add.at(cnt, (kk // NV - rects[x][0], kk % NV - (g.vpitch * rr - VBAND_LO)), 1)
            low = tot[xi] <= q25                                            # lowest-quartile tiles = least-used
            ml = m & np.isin(orr, np.flatnonzero(low) + 1)
            kk, rr = keys[ml], orr[ml]
            np.add.at(cnt_lo, (kk // NV - rects[x][0], kk % NV - (g.vpitch * rr - VBAND_LO)), 1)
        nt, nlo = flat.size, int((tot <= q25).sum())
        out[f"{kname}_tiles"] = dict(columns=len(xs), tiles=int(nt), zero_set_tiles=int((flat == 0).sum()),
                                     set_total=int(flat.sum()), cells_per_tile=int(cells.ravel()[0]),
                                     quantiles=[int(q) for q in np.quantile(flat, [0, .1, .25, .5, .75, .9, 1])],
                                     rel_cells_over_half=int((cnt / nt > .5).sum()), rel_cells_over_90=int((cnt / nt > .9).sum()),
                                     set_bits_in_over_90_cells=int(cnt[cnt / nt > .9].sum()),
                                     lowest_quartile_tiles=nlo, lowq_cells_over_half=int((cnt_lo / max(nlo, 1) > .5).sum()),
                                     lowq_cells_over_90=int((cnt_lo / max(nlo, 1) > .9).sum()),
                                     lowq_max_set=int(q25), lowq_set_bits_total=int(cnt_lo.sum()))
    return out


def other_images(C, g, nper, meta_img, sm_img):
    """Per-class set fractions + idle stats for the other GX150 corpus images (class layout shared, 2a/2b merged)."""
    res = {}
    allset = sm_img.copy()
    for p in sorted(glob.glob(str(REPO / "sources/cycloneiv-corpus/*/*.rbf"))):
        name = Path(p).parent.name
        raw = Path(p).read_bytes()
        try:
            plane, sm, meta = load_image(raw, g)
        except Exception as e:                                              # other die: reported in ce_images
            continue
        if meta["nfr"] != meta_img["nfr"]:
            continue
        allset &= sm
        cm = C.cls.copy()
        cm[cm == CID["2a"]] = CID["2b"]
        cnt, st = np.bincount(cm, minlength=NCLS), np.bincount(cm[sm], minlength=NCLS)
        res[name] = dict(plane_set=meta["plane_set"], plane_set_frac=meta["plane_set"] / ((meta["nfr"] - 1) * NV),
                         per_class={IDS[i - 1]: round(float(st[i] / cnt[i]), 4) for i in range(1, NCLS) if cnt[i] and IDS[i - 1] not in ("2a", "5a")},
                         header_set=meta["hdr_set"], crc_frac=meta["crc_set"] / ((meta["nfr"] - nper) * 16))
        log.info("other GX150 image %s: %d set bits (%.3f)", name, meta["plane_set"], res[name]["plane_set_frac"])
    k = np.flatnonzero(allset)
    fr = k // NV
    res["_set_in_all_6_images"] = dict(cells=int(len(k)), per_class={IDS[c - 1]: int(n) for c, n in enumerate(np.bincount(C.cls[k], minlength=NCLS)) if n and c},
                                      in_periphery_frames=int((fr < meta_img["nper"]).sum()), distinct_frames=int(len(np.unique(fr))))
    return res


def ce_images():
    """EP4CE (and other-die) images: frame-level polarity numbers only (no tile geometry used)."""
    import cycloneiv_decompress as cd
    res = {}
    for p in sorted(glob.glob(str(REPO / "sources/cycloneiv-corpus/*/*.rbf"))):
        name = Path(p).parent.name
        try:
            info = {}
            u = cd.decompress(Path(p).read_bytes(), info)
        except Exception as e:
            res[name] = dict(error=str(e)[:80]); continue
        F, nper, ncram = info["frame"], info["periphery_frames"], info["cram_frames"]
        nfr = nper + ncram
        a = np.frombuffer(u, np.uint8)
        fr_bits = lambda f, lo, hi: np.unpackbits(a[cd.PREAMBLE + f * F + lo:cd.PREAMBLE + f * F + hi])
        hdr = int(fr_bits(0, 0, F).sum())
        per = sum(int(fr_bits(f, 0, F).sum()) for f in range(1, nper))
        data = [int(fr_bits(f, 0, F - 2).sum()) for f in range(nper, nfr)]
        crc = sum(int(fr_bits(f, F - 2, F).sum()) for f in range(nper, nfr))
        d = np.array(data) / ((F - 2) * 8)
        res[name] = dict(frame_bytes=F, periphery_frames=nper - 1, cram_frames=ncram, header_frac=hdr / (F * 8),
                         periphery_frac=per / max((nper - 1) * F * 8, 1), cram_data_frac=float(sum(data) / (ncram * (F - 2) * 8)),
                         crc_frac=crc / (ncram * 16), cram_frames_over_half=int((d > .5).sum()), cram_max_frame_frac=float(d.max()))
    return res


# ---------------------------------------------------------------------------------------------
# part 2: html
# ---------------------------------------------------------------------------------------------
PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Known cells on the die</title>
<style>
:root{--bg:#fbfbfa;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#d9d8d3;--ver:#2f9e6a;--evi:#e0a31b;--unk:#9a9992;--ovh:#4f7fd0;--bad:#d23a3a;--lab:#4f7fd0;--m9k:#9b59b6;--mul:#d9693a;--io:#3aa7a7;--accent:#2a5bd7}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#17181a;--fg:#e8e8e4;--mut:#9a9a94;--card:#202225;--line:#38393c;--ver:#46c08a;--evi:#f0b93a;--unk:#6c6d71;--ovh:#6c9bf0;--bad:#ff6b6b;--lab:#6c9bf0;--m9k:#c08be0;--mul:#f08a5a;--io:#55c4c4;--accent:#7fa2ff}}
:root[data-theme=dark]{--bg:#17181a;--fg:#e8e8e4;--mut:#9a9a94;--card:#202225;--line:#38393c;--ver:#46c08a;--evi:#f0b93a;--unk:#6c6d71;--ovh:#6c9bf0;--bad:#ff6b6b;--lab:#6c9bf0;--m9k:#c08be0;--mul:#f08a5a;--io:#55c4c4;--accent:#7fa2ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;padding:16px}
h1{font-size:20px;margin:0 0 2px}p.sub{margin:0 0 12px;color:var(--mut)}
.wrap{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:16px;margin:0 auto}
@media (max-width:900px){.wrap{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:12px}
canvas{display:block;border-radius:6px;cursor:crosshair;max-width:100%}
.scroll{overflow:auto;max-height:78vh}
fieldset{border:0;padding:0;margin:0 0 10px}legend{font-weight:600;margin-bottom:4px}
label{display:flex;gap:6px;align-items:center;margin:2px 0;cursor:pointer}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block;flex:none}
#info{min-height:150px;font-variant-numeric:tabular-nums}#info b{font-weight:600}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}td,th{padding:1px 3px}td:not(:first-child),th:not(:first-child){text-align:right}
th{font-weight:600;color:var(--mut);border-bottom:1px solid var(--line)}
.note{color:var(--mut);font-size:12px;margin-top:8px}
#bm{image-rendering:pixelated;cursor:crosshair}
input[type=range]{width:100%}
.blegend{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:2px 12px;margin-top:8px}.blegend b,.blegend .note{grid-column:1/-1}
@media (min-width:901px){.wrap>div:last-child{position:sticky;top:0;align-self:start;max-height:calc(100vh - 16px);overflow:auto}}
/*__PINS_CSS__*/
</style></head><body>
<h1>EP4CGX150 die: which cells of one image are known</h1>
<p class="sub">One tile per cell (x across, y up). Data: a single third-party EP4CGX150 image classified by the bit inventory. Click a tile to inspect its cells.</p>
<div class="wrap">
<div>
<div class="card" style="overflow:auto"><canvas id="c" role="img" aria-label="Die tile map, colour by known share of the image's set bits"></canvas></div>
<div class="card" id="insp"><b>Tile inspector</b> <span id="ititle" style="color:var(--mut)">click a tile on the map</span>
<div class="blegend"><b>Bitmap legend</b>
<label style="cursor:default"><span class="sw" style="background:var(--ver)"></span>verified class, set</label>
<label style="cursor:default"><span class="sw" style="background:var(--evi)"></span>evidence class, set</label>
<label style="cursor:default"><span class="sw" style="background:var(--unk)"></span>unknown class, set</label>
<label style="cursor:default"><span class="sw" style="background:var(--ovh)"></span>CRC bytes (checksum), set</label>
<label><input type="checkbox" id="tint" checked> Tint unset cells by their class tier</label>
<label><input type="checkbox" id="onlyset"> Only set cells</label>
<label>Cell size <input type="range" id="csz" min="0" max="16" value="0"></label>
<div class="note">Verified = LUT INIT bits (compared with vendor netlists, 100 % over 301 builds). Evidence = a mapping exists without a per-bit oracle (LE-used bit, clock polarity, routing tables, translated routing specimens). Unknown = no meaning attributed. Evidence also covers table-only routing cells: <i>known</i> here means "has a proposed meaning", and is weaker than verified.</div>
<div class="scroll" style="max-height:560px;margin-top:8px"><canvas id="bm" width="10" height="10"></canvas></div>
<div id="bmi" class="note" style="min-height:2.6em">Frames run left to right, v runs upward. Hover a cell.</div></div>
</div>
<div>
<div class="card">
<fieldset><legend>Colour by</legend>
<label><input type="radio" name="mode" value="share" checked> (a) Known share of set bits</label>
<label><input type="radio" name="mode" value="dens"> (b) Set-bit density of the image</label>
<label><input type="radio" name="mode" value="cap"> (c) Known-cell capacity (die-wide)</label>
<label><input type="radio" name="mode" value="kind"> (d) Tile kind</label></fieldset>
<fieldset><legend>Show tiles</legend>
<label><input type="checkbox" data-k="LAB" checked><span class="sw" style="background:var(--lab)"></span>LAB</label>
<label><input type="checkbox" data-k="M9K" checked><span class="sw" style="background:var(--m9k)"></span>M9K memory</label>
<label><input type="checkbox" data-k="MUL" checked><span class="sw" style="background:var(--mul)"></span>Multiplier</label>
<label><input type="checkbox" data-k="IO" checked><span class="sw" style="background:var(--io)"></span>IO (ring)</label></fieldset>
<fieldset><legend>Overlays</legend>
<label><input type="checkbox" id="oZero" checked><span class="sw" style="border:2px solid var(--bad)"></span>Set bits but none known</label>
<label><input type="checkbox" id="oSel" checked> Selected tile</label>
<label><input type="checkbox" id="fit" checked> Fit map to window</label>
<label>Map zoom <input type="range" id="zoom" min="6" max="56" value="10"></label></fieldset>
<div id="legend"></div></div>
<div class="card"><div id="info">Hover a tile.</div></div>
<!--__PINS_HTML__-->
<div class="note">Row binning is by band [VY-68, VY+1] (70 v). Cells of classes 1, 2 and 3 are owned by the tile that generated them; the rest are binned by frame band and v row. Frames FX+16..FX+17 of a LAB column are shared with the next column band.</div>
</div></div>
<script>
const D=__DATA__;
const NX=D.nx,NY=D.ny,T=D.t,CL=D.cls,KN=D.kinds;
// tile row: [x,y,kind,cells,set,sv,se,su,so,capv,cape,s2a,fa,w,tmpl]
const grid=new Map();T.forEach(t=>grid.set(t[0]*1000+t[1],t));
const cv=document.getElementById('c'),ctx=cv.getContext('2d');let S=10,M=2;
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const kv=k=>(k=="IOL"||k=="IOR"||k=="IOROW")?"IO":k;
const TV={V:'--ver',E:'--evi',U:'--unk',O:'--ovh'};
let mode="share",hover=null,sel=null;const vis={LAB:1,M9K:1,MUL:1,IO:1};
const maxDens=Math.max(...T.map(t=>t[3]?t[4]/t[3]:0));
function ramp(f){f=Math.max(0,Math.min(1,f));const a=[247,247,240],b=[34,70,160];return `rgb(${a.map((x,i)=>Math.round(x+(b[i]-x)*f)).join(',')})`}
function fitS(){const card=cv.parentElement,w=card.clientWidth-26,top=card.getBoundingClientRect().top;const h=Math.max(360,innerHeight-Math.max(top,0)-28);return Math.max(4,Math.min(56,Math.floor(Math.min((w-2*M)/NX,(h-2*M)/NY))))}
let fit=true;function setFit(on){fit=on;const e=document.getElementById('fit');if(e)e.checked=on}
function size(){if(fit){S=fitS();document.getElementById('zoom').value=S}const w=NX*S+2*M,h=NY*S+2*M;if(cv.width!=w)cv.width=w;if(cv.height!=h)cv.height=h}
function setZoom(v){setFit(false);S=v;document.getElementById('zoom').value=v;draw()}
function tile(t,px,py){const k=kv(KN[t[2]]);
 if(mode=="share"){const tot=t[5]+t[6]+t[7];ctx.fillStyle=css('--line');ctx.globalAlpha=.4;ctx.fillRect(px,py,S-1,S-1);ctx.globalAlpha=1;
  if(tot>0){let y=py+S-1;for(const [n,c] of [[t[5],'--ver'],[t[6],'--evi'],[t[7],'--unk']]){const h=(S-1)*n/tot;ctx.fillStyle=css(c);ctx.fillRect(px,y-h,S-1,h);y-=h}}}
 else if(mode=="dens"){ctx.fillStyle=ramp(Math.sqrt((t[3]?t[4]/t[3]:0)/maxDens));ctx.fillRect(px,py,S-1,S-1)}
 else if(mode=="cap"){ctx.fillStyle=ramp((t[9]+t[10])/Math.max(t[3],1));ctx.fillRect(px,py,S-1,S-1)}
 else{ctx.fillStyle=css('--'+{LAB:'lab',M9K:'m9k',MUL:'mul',IO:'io'}[k]);ctx.fillRect(px,py,S-1,S-1)}}
function draw(){size();const w=cv.width,h=cv.height;ctx.clearRect(0,0,w,h);ctx.fillStyle=css('--card');ctx.fillRect(0,0,w,h);
 const z=document.getElementById('oZero').checked;
 for(const t of T){const k=kv(KN[t[2]]);const px=M+t[0]*S,py=M+(NY-1-t[1])*S;
  if(!vis[k]){ctx.fillStyle=css('--line');ctx.globalAlpha=.3;ctx.fillRect(px,py,S-1,S-1);ctx.globalAlpha=1;continue}
  tile(t,px,py);
  if(z&&(t[5]+t[6]+t[7])>0&&(t[5]+t[6])==0){ctx.strokeStyle=css('--bad');ctx.lineWidth=1.5;ctx.strokeRect(px+.5,py+.5,S-2,S-2)}}
 const o=document.getElementById('oSel').checked;
 for(const [t,c] of [[sel,'--accent'],[hover,'--fg']]){if(!t||(t===sel&&!o))continue;const px=M+t[0]*S,py=M+(NY-1-t[1])*S;ctx.strokeStyle=css(c);ctx.lineWidth=2;ctx.strokeRect(px-1,py-1,S+1,S+1)}
 pinsDraw();legend()}
function legend(){const L=document.getElementById('legend');let h="";
 if(mode=="share")h=[['--ver','verified-class set bits'],['--evi','evidence-class'],['--unk','unknown-class']].map(([c,n])=>`<label style="cursor:default"><span class="sw" style="background:${css(c)}"></span>${n}</label>`).join("")+`<div class="note" style="margin:2px 0 0">Bar height = share of the tile's set bits (CRC bytes excluded).</div>`;
 else if(mode=="kind")h=["LAB","M9K","MUL","IO"].map(x=>`<label style="cursor:default"><span class="sw" style="background:${css('--'+{LAB:'lab',M9K:'m9k',MUL:'mul',IO:'io'}[x])}"></span>${x}</label>`).join("");
 else{const m=mode=="dens"?maxDens:1;h=`<div style="height:10px;border-radius:3px;background:linear-gradient(90deg,${ramp(0)},${ramp(1)})"></div><div class="note" style="margin:2px 0 0;display:flex;justify-content:space-between"><span>0</span><span>${mode=="dens"?"set / cells (sqrt scale), max "+(100*maxDens).toFixed(1)+" %":"known cells / cells, 100 %"}</span></div>`}
 L.innerHTML=h}
// ---- decoded blobs
let CT=null,SB=null,SOFF=null;
async function inflate(b64){const bin=atob(b64),u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);
 return new Uint8Array(await new Response(new Blob([u]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer())}
async function init(){try{CT=await inflate(D.C);SB=await inflate(D.S);
 SOFF=new Array(T.length);let o=0;T.forEach((t,i)=>{SOFF[i]=o;o+=Math.ceil(t[13]*70/8)});}catch(e){document.getElementById('bmi').textContent="Bitmaps need DecompressionStream (a current browser)."}
 draw()}
function cellsOf(t){const i=T.indexOf(t);return {off:D.tp[t[14]][0],soff:SOFF[i],w:t[13]}}
function bit(soff,k){return (SB[soff+(k>>3)]>>(7-(k&7)))&1}
function breakdown(t){ // per class: cells, set
 if(!CT)return "";const c=cellsOf(t),n=new Array(CL.length+1).fill(0),s=new Array(CL.length+1).fill(0);
 for(let i=0;i<t[13];i++)for(let r=0;r<70;r++){const k=i*70+r,cl=CT[c.off+k];if(!cl)continue;n[cl]++;if(bit(c.soff,k))s[cl]++}
 let h="<table><tr><th>class</th><th>cells</th><th>set</th></tr>";
 for(let q=1;q<=CL.length;q++)if(n[q]){h+=`<tr><td><span class="sw" style="background:${css(TV[CL[q-1][1]])};margin-right:4px"></span>${CL[q-1][0]}</td><td>${n[q]}</td><td>${s[q]}</td></tr>`}
 return h+"</table>"}
const pc=(a,b)=>b?(100*a/b).toFixed(1)+" %":"-";
function infoHtml(t){const tot=t[5]+t[6]+t[7];
 return `<b>X${t[0]} Y${t[1]}</b> &nbsp;${KN[t[2]]}<table><tr><td>Cells in tile</td><td>${t[3].toLocaleString()}</td></tr><tr><td>Image set bits</td><td>${t[4].toLocaleString()} (${pc(t[4],t[3])})</td></tr>
 <tr><td>verified / evidence / unknown set</td><td>${t[5]} / ${t[6]} / ${t[7]}</td></tr><tr><td>Known share of set bits</td><td>${pc(t[5]+t[6],tot)}</td></tr>
 <tr><td>of which routing cells fired by decode</td><td>${t[11]}</td></tr><tr><td>CRC-byte set bits (excluded)</td><td>${t[8]}</td></tr>
 <tr><td>Known-cell capacity</td><td>${(t[9]+t[10]).toLocaleString()} (${pc(t[9]+t[10],t[3])}); verified ${t[9]}</td></tr></table>`+breakdown(t)}
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect(),sx=cv.width/r.width;const x=Math.floor(((e.clientX-r.left)*sx-M)/S),y=NY-1-Math.floor(((e.clientY-r.top)*sx-M)/S);
 const t=grid.get(x*1000+y);hover=t||null;draw();const I=document.getElementById('info');I.innerHTML=t?infoHtml(t):"Hover a tile."});
cv.addEventListener('mouseleave',()=>{hover=null;draw()});
cv.addEventListener('click',e=>{const r=cv.getBoundingClientRect(),sx=cv.width/r.width;const x=Math.floor(((e.clientX-r.left)*sx-M)/S),y=NY-1-Math.floor(((e.clientY-r.top)*sx-M)/S);
 const t=grid.get(x*1000+y);if(t){sel=t;inspect(t);draw()}});
// ---- inspector bitmap
const bm=document.getElementById('bm'),bx=bm.getContext('2d');let bsel=null,bsc=1;
function inspect(t){bsel=t;document.getElementById('ititle').textContent=`X${t[0]} Y${t[1]} ${KN[t[2]]}: frames ${t[12]}..${t[12]+t[13]-1}, ${t[13]} x 70 cells`;drawBm()}
function drawBm(){const t=bsel;if(!t||!CT)return;const c=cellsOf(t),w=t[13];
 const z=+document.getElementById('csz').value;bsc=z||Math.max(1,Math.min(14,Math.floor(900/w)));
 bm.width=w*bsc;bm.height=70*bsc;const tint=document.getElementById('tint').checked,only=document.getElementById('onlyset').checked;
 bx.fillStyle=css('--card');bx.fillRect(0,0,bm.width,bm.height);
 const col={};for(const k in TV)col[k]=css(TV[k]);
 for(let i=0;i<w;i++)for(let r=0;r<70;r++){const k=i*70+r,cl=CT[c.off+k];if(!cl)continue;const s=bit(c.soff,k),tr=CL[cl-1][1];
  if(!s&&(only||!tint))continue;bx.globalAlpha=s?1:.16;bx.fillStyle=col[tr];bx.fillRect(i*bsc,(69-r)*bsc,bsc>2?bsc-1:bsc,bsc>2?bsc-1:bsc)}
 bx.globalAlpha=1}
bm.addEventListener('mousemove',e=>{const t=bsel;if(!t||!CT)return;const rc=bm.getBoundingClientRect(),sx=bm.width/rc.width;
 const i=Math.floor((e.clientX-rc.left)*sx/bsc),r=69-Math.floor((e.clientY-rc.top)*sx/bsc);if(i<0||i>=t[13]||r<0||r>69)return;
 const c=cellsOf(t),k=i*70+r,cl=CT[c.off+k];const v=70*t[1]-48+r;
 document.getElementById('bmi').innerHTML=cl?`frame ${t[12]+i}, v ${v} (tile row ${r}): class <b>${CL[cl-1][0]}</b> ${CL[cl-1][2]} [${{V:'verified',E:'evidence',U:'unknown',O:'overhead'}[CL[cl-1][1]]}], ${bit(c.soff,k)?'<b>set</b>':'clear'}`:`frame ${t[12]+i}, v ${v}: not owned by this tile`});
['tint','onlyset','csz'].forEach(id=>document.getElementById(id).oninput=drawBm);
document.querySelectorAll('input[name=mode]').forEach(i=>i.onchange=()=>{mode=i.value;draw()});
document.querySelectorAll('[data-k]').forEach(i=>i.onchange=()=>{vis[i.dataset.k]=i.checked?1:0;draw()});
['oZero','oSel'].forEach(id=>document.getElementById(id).onchange=draw);
document.getElementById('zoom').oninput=e=>{setFit(false);S=+e.target.value;draw()};
document.getElementById('fit').onchange=e=>{fit=e.target.checked;draw()};addEventListener('resize',()=>{if(fit)draw()});

matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>{draw();drawBm()});
/*__PINS_JS__*/
init();
</script></body></html>
"""


def emit_html(rows, blobs, g, cls_info):
    kidx = {k: i for i, k in enumerate(KINDS)}
    t = [[r["x"], r["y"], kidx[r["kind"]], r["cells"], r["set"], r["set_ver"], r["set_evi"], r["set_unk"], r["set_ovh"],
          r["cap_ver"], r["cap_evi"], r["cls_set"].get("2a", 0), r["fa"], r["w"], r["tmpl"]] for r in rows]
    data = dict(nx=g.xmax + 1, ny=YROWS, kinds=KINDS, t=t, cls=cls_info, **blobs)
    (GEO / "image_overlay_data.json").write_text(json.dumps(data, separators=(",", ":")))
    write_page(data)


def write_page(data):
    """Page = embedded tile data + pin layer from device_pins (scripts/geo_pins.py, docs/geo-pins.md)."""
    pins = geo_pins.load_pins()
    html = geo_pins.inject(PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":"))), pins)
    (GEO / "image_overlay.html").write_text(html)
    log.info("wrote image_overlay.html %.2f MB, %d pins (%d with die site)", len(html) / 1e6, len(pins["p"]), sum(r[4] is not None for r in pins["p"]))


# ---------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--repin", action="store_true", help="rebuild image_overlay.html from tmp/geo/image_overlay_data.json (no image, light)")
    ap.add_argument("--stage", default="all", choices=("all", "attrib", "encoding"))
    a = ap.parse_args()
    if not a.image and not a.repin:
        ap.error("--image or --repin required")
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    GEO.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/geo_image_overlay.log", "w")])
    if a.repin:
        write_page(json.loads((GEO / "image_overlay_data.json").read_text()))
        return
    import heavy_guard
    bi.need_ram(20)
    blobs = None
    with heavy_guard.lease(4.0, "image_overlay", log):
        import cycloneiv_asm_decode as ad
        import cycloneiv_geom as cg
        g = cg.load(cg.die_of("EP4CGX150"))
        plane, sm, meta = load_image(Path(a.image).read_bytes(), g)
        nfr, nper = meta["nfr"], meta["nper"]
        log.info("image: %d frames, %d plane set bits, header %d, crc %d", nfr, meta["plane_set"], meta["hdr_set"], meta["crc_set"])
        dec = ad.Dec()
        C, tiles, fired, asm_any = classify(g, plane, nfr, nper, dec)
        H, Hs = tile_hist(C, sm, g)
        rows = build_table(H, Hs, g)
        write_tables(rows, g.xmax + 1)
        # die-wide totals by tier for the log
        for nm, A in (("cells", H), ("image set", Hs)):
            log.info("%s in tiles: verified %d evidence %d unknown %d overhead %d", nm, *(int(tier_sum(A, t).sum()) for t in "VEUO"))
        extra = {IDS[c - 1]: (int(((C.ocol < 0) & (C.cls == c)).sum()), int((((C.ocol < 0) & (C.cls == c)) & sm).sum())) for c in range(1, NCLS)
                 if ((C.ocol < 0) & (C.cls == c)).any()}
        log.info("cells with no tile (class: cells, set): %s; header set %d", extra, meta["hdr_set"])
        if a.stage in ("all", "attrib"):
            blobs = pack_bitmaps(C, sm, g, rows, nper, nfr)
            cls_info = [[cid, TIER[i + 1], name] for i, (cid, name, _t) in enumerate(CLS)]
            # emit_html runs after the lease is released
        if a.stage in ("all", "encoding"):
            enc = encoding(C, sm, plane, dec, g, tiles, meta, H, Hs, fired)
            enc["outside_tiles"] = extra
            enc["other_gx150_images"] = other_images(C, g, nper, meta, sm)
            enc["other_die_images"] = ce_images()
            (GEO / "image_encoding.json").write_text(json.dumps(enc, indent=1))
            log.info("wrote image_encoding.json")

    if blobs is not None:
        emit_html(rows, blobs, g, cls_info)

if __name__ == "__main__":
    main()
