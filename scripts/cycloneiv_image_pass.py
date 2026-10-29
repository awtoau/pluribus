#!/usr/bin/env python3.15t
"""Realism pass of an unknown Cyclone IV GX150 image against Quartus-built corpus designs and a
control: does the decode look like real logic (corpus-like) or like noise (shuffled-control-like)?

Subjects (each reduced to a SparsePlane of set CRAM bits):
  image    : the file given with --image (read only, never copied)
  corpus   : --corpus designs (held-out half of gx150_sp_*, built by Quartus)
  control  : the image with its set bits shuffled inside every frame (same bits per frame)

Sections (all with the same functions applied to every subject):
  1 LUT masks    decoded for all 104 x 90 x 16 LAB LEs: used-LE count (mask != 0 or LE-used bit),
                 constant / 1-input / small-support fractions, distinct masks, carry-mask cells
  2 routing      learnt tables (pooled X mod 8) applied to the routing bits of active LABs:
                 mux reads as zero / one known source / ambiguous / nonzero-unknown
  3 netlist      sampled LE inputs traced to drivers (cycloneiv_route_decode.Tracer): inputs the
                 mask depends on that trace to a unique driver, comb loops, driver fan-in
  4 IO           sites whose configuration signature (cycloneiv_io_bits.py) is fully set
  5 claims       set bits explained by the decode (LUT-mask bits, routing mux bits, IO signatures,
                 bits set in >= STATIC_FRAC of the corpus) vs unclaimed

  python3.15t scripts/cycloneiv_image_pass.py --image PATH --tables tmp/cycloneiv/rl_gx_m8.json
Log tmp/logs/cycloneiv_image_pass.log (memory: planes are ~1-18 MB, run under a <= 2 GB cgroup)
"""
import argparse
import collections
import json
import logging
import random
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_le_locate as ll  # noqa: E402
import cycloneiv_route_decode as rd  # noqa: E402
import cycloneiv_common as ccm  # noqa: E402

log = logging.getLogger("cycloneiv_image_pass")
STATIC_FRAC = 0.95      # a bit set in this fraction of corpus designs is static configuration
SAMPLE_TILES = 600      # active LABs sampled for the routing classification
SAMPLE_LES = 150        # LEs whose input cone is traced
CONE_CAP = 2500         # nodes per traced cone
CARRY_TOP = 8           # carry masks = most common masks among corpus arithmetic cells


def lab_tiles(geom):
    return [(x, y) for x in sorted(geom.kind) if geom.kind[x] == "LAB" for y in range(1, geom.ymax)]


def le_positions(geom, tiles, df, dv):
    """(frame, v) arrays for bit (df, dv) of every LE of the tiles, order tile-major, LE 0..15."""
    f, v = [], []
    for x, y in tiles:
        f0, v0 = geom.anchor(x, y)
        for le in range(16):
            s = -1 if le % 2 else 1
            f.append(f0 + df)
            v.append(v0 + geom.DN[le] + s * dv)
    return np.array(f), np.array(v)


def decode_masks(plane, geom, tiles):
    masks = np.zeros(len(tiles) * 16, dtype=np.uint32)
    for k, (df, dv) in enumerate(ll.DK):
        f, v = le_positions(geom, tiles, df, dv)
        masks |= plane.has(f, v).astype(np.uint32) << k
    f, v = le_positions(geom, tiles, -8, -1)
    usedbit = plane.has(f, v)
    return masks.astype(np.uint16), usedbit


def support(masks):
    """number of the 4 inputs the 16-bit truth table depends on (index = a + 2b + 4c + 8d)."""
    m = masks.astype(np.uint32)
    n = np.zeros(len(m), dtype=np.int8)
    for i in range(4):
        dep = np.zeros(len(m), dtype=bool)
        for j in range(16):
            if j >> i & 1:
                continue
            dep |= ((m >> j) & 1) != ((m >> (j | (1 << i))) & 1)
        n += dep
    return n


def lut_stats(name, plane, geom, tiles, carry_masks):
    masks, usedbit = decode_masks(plane, geom, tiles)
    used = (masks != 0) | usedbit
    um = masks[used]
    sup = support(um) if len(um) else np.zeros(0, dtype=np.int8)
    cnt = collections.Counter(um.tolist())
    out = {"LEs": len(masks), "used": int(used.sum()), "used_bit_only": int((usedbit & (masks == 0)).sum()),
           "mask_nonzero": int((masks != 0).sum())}
    n = max(len(um), 1)
    out["const"] = float(((um == 0) | (um == 0xFFFF)).sum() / n)
    for s in range(5):
        out[f"support{s}"] = float((sup == s).sum() / n)
    out["distinct_masks"] = len(cnt)
    out["carry_cells"] = int(sum(c for m_, c in cnt.items() if m_ in carry_masks))
    top = cnt.most_common(6)
    out["top_masks"] = [(f"{m_:04x}", c) for m_, c in top]
    log.info("[LUT] %-10s LEs %d, used %d (mask!=0 %d, used-bit-only %d); const %.3f; support 0..4: %s; "
             "distinct %d; carry-mask cells %d; top %s", name, out["LEs"], out["used"], out["mask_nonzero"],
             out["used_bit_only"], out["const"], [round(out[f"support{s}"], 3) for s in range(5)],
             out["distinct_masks"], out["carry_cells"], out["top_masks"])
    return out, masks, used


def active_tiles(used, tiles):
    u = used.reshape(len(tiles), 16).any(1)
    return [t for t, a in zip(tiles, u) if a]


def route_classes(dec, plane, geom, tiles, rng):
    t = dec.tables[0]
    cats = collections.Counter()
    groups_read = 0
    for (x, y) in tiles:
        cls = ccm.tile_class(geom, x, y, t.col_phase)
        for key, (mux, pats, (ax, ay)) in dec.groups_in_class(t, cls):
            if not mux or key[0] in ("LCCOMB", "FF"):
                continue
            bits = rd.read_bits(plane, geom, x + ax, y + ay, mux)
            groups_read += 1
            if not bits:
                cats["zero"] += 1
                continue
            got = pats.get(bits)
            cats["unknown" if got is None else "known" if len(got) == 1 else "ambiguous"] += 1
    return cats, groups_read


def netlist_stats(dec, plane, geom, tiles, masks, rng):
    """Trace sampled LE inputs; loops over LCCOMB -> LCCOMB edges; driver kinds."""
    tidx = {t: i for i, t in enumerate(tiles)}
    tr = rd.Tracer(dec, plane, geom)
    ports = ["DATAA", "DATAB", "DATAC", "DATAD"]
    res = collections.Counter()
    why = collections.Counter()
    drivers = collections.Counter()
    edges = {}
    fan = collections.Counter()

    def inputs_of(x, y, le):
        i = tidx.get((x, y))
        if i is None:
            return None
        m = int(masks[i * 16 + le])
        dep = support_deps(m)
        out = []
        for p, d in zip(ports, dep):
            if not d:
                continue
            got, reason = tr.trace(("LCCOMB", 2 * le, p), x, y)
            if got is None:
                res["input_unresolved"] += 1
                why[reason.split(":")[0]] += 1
            else:
                res["input_resolved"] += 1
                drivers[got[1]] += 1
                fan[got] += 1
                out.append(got)
        return out
    seeds = [(t, le) for t in tiles for le in range(16) if masks[tidx[t] * 16 + le]]
    rng.shuffle(seeds)
    seen, loops = set(), 0
    for (x, y), le in seeds[:SAMPLE_LES]:
        stack = [((x, y, le), 0)]
        onpath = set()
        order = []
        # iterative DFS with colouring for cycle detection over comb nodes
        color = {}
        todo = [(x, y, le)]
        while todo and len(seen) < CONE_CAP:
            node = todo[-1]
            if node not in color:
                color[node] = 1
                if node not in edges:
                    edges[node] = [(d[3], d[4], d[2] // 2) for d in (inputs_of(*node) or []) if d[1] == "LCCOMB"]
                    res["nodes_expanded"] += 1
                seen.add(node)
                pend = [c for c in edges[node] if color.get(c) is None]
                todo.extend(pend)
                for c in edges[node]:
                    if color.get(c) == 1:
                        loops += 1
            else:
                color[node] = 2
                todo.pop()
    res["comb_loops"] = loops
    return res, why, drivers, fan


def support_deps(m):
    dep = []
    for i in range(4):
        d = False
        for j in range(16):
            if j >> i & 1:
                continue
            if ((m >> j) & 1) != ((m >> (j | (1 << i))) & 1):
                d = True
                break
        dep.append(d)
    return dep


def io_stats(plane, io_sigs):
    n = collections.Counter()
    edges = collections.Counter()
    sites = []
    for kind, sigs in io_sigs.items():
        for site, bits in sigs.items():
            bits = [b for b in bits if b[0] < plane.shape[0] and b[1] < plane.shape[1]]
            if not bits:
                continue
            f = np.array([b[0] for b in bits])
            v = np.array([b[1] for b in bits])
            if plane.has(f, v).all():
                x, y, nn = map(int, site.split(","))
                n[kind] += 1
                edges[(kind, "bottom" if y == 0 else "top" if y == 91 else "left" if x == 0 else "right")] += 1
                sites.append((kind, site))
    return n, edges, sites


def load_io_sigs():
    sig = {}
    for kind in ("IOOBUF", "IOIBUF"):
        p = REPO / "tmp" / "cycloneiv" / f"io_bits_{kind}.json"
        d = json.loads(p.read_text())
        sig[kind] = {k: [tuple(b) for b in v["bits"]] for k, v in d.items() if v["pos"] >= 12 and v["bits"]
                     and len(v["bits"]) < 100}
    return sig


def shuffle_control(plane, seed):
    """per-frame shuffle: same number of set bits in every frame, random v within the frame."""
    nf, nv = plane.shape
    rng = np.random.default_rng(seed)
    fr = plane.keys // nv
    keys = []
    for f in np.unique(fr):
        n = int((fr == f).sum())
        keys.append(f * nv + rng.choice(nv, n, replace=False))
    return cc.SparsePlane(np.sort(np.concatenate(keys)).astype(np.int64), nf, nv)


def claims(plane, geom, tiles, dec, io_sigs, static_keys):
    """set bits explained by: LUT-mask + used bit, routing mux positions of every LAB tile, IO
    signatures, static bits.  -> dict of counts."""
    keys = plane.keys
    nf, nv = plane.shape
    hit = {"lut": np.zeros(len(keys), dtype=bool), "route": np.zeros(len(keys), dtype=bool),
           "io": np.zeros(len(keys), dtype=bool), "static": np.zeros(len(keys), dtype=bool)}

    def flag(name, k):
        k = np.unique(k[(k >= 0)])
        i = np.searchsorted(keys, k)
        i = np.minimum(i, len(keys) - 1)
        ok = keys[i] == k
        hit[name][i[ok]] = True
    for df, dv in ll.DK + [(-8, -1)]:
        f, v = le_positions(geom, tiles, df, dv)
        flag("lut", f * nv + v)
    t = dec.tables[0]
    fx = np.array([geom.FX.get(x, -10**6) for x in range(geom.xmax + 1)])
    by_cls = collections.defaultdict(list)
    for (x, y) in tiles:
        by_cls[ccm.tile_class(geom, x, y, t.col_phase)].append((x, y))
    for cls, tl in by_cls.items():
        rows = []
        for key, (mux, pats, (ax, ay)) in dec.groups_in_class(t, cls):
            for df, dv in mux:
                rows.append((ax, ay, df + ccm.WF[0], dv + ccm.WV[0]))
        rows = np.unique(np.array(rows, dtype=np.int64), axis=0) if rows else np.zeros((0, 4), dtype=np.int64)
        for (x, y) in tl:
            xs = x + rows[:, 0]
            ys = y + rows[:, 1]
            ok = (xs >= 0) & (xs <= geom.xmax) & (ys >= 0) & (ys <= geom.ymax)
            f = fx[xs[ok]] + rows[ok, 2]
            v = geom.vy0 + geom.vpitch * ys[ok] + rows[ok, 3]
            inb = (f >= 0) & (f < nf) & (v >= 0) & (v < nv)
            flag("route", f[inb] * nv + v[inb])
    for kind, sigs in io_sigs.items():
        for site, bits in sigs.items():
            k = np.array([b[0] * nv + b[1] for b in bits if b[0] < nf and b[1] < nv], dtype=np.int64)
            flag("io", k)
    flag("static", static_keys)
    any_ = np.zeros(len(keys), dtype=bool)
    for h in hit.values():
        any_ |= h
    out = {"set_bits": len(keys), "unclaimed": int((~any_).sum())}
    for n, h in hit.items():
        out[n] = int(h.sum())
    out["claimed"] = int(any_.sum())
    return out


def static_bits(names):
    nf = nv = None
    cnt = None
    for n in names:
        d = cc.load_plane_only(n)
        if cnt is None:
            nf, nv = d.shape
            cnt = np.zeros(nf * nv, dtype=np.uint16)
        cnt[d.keys] += 1
    return np.flatnonzero(cnt >= STATIC_FRAC * len(names)).astype(np.int64)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True)
    ap.add_argument("--tables", default=str(REPO / "tmp" / "cycloneiv" / "rl_gx_m8.json"))
    ap.add_argument("--corpus", type=int, default=6, help="number of held-out corpus designs")
    ap.add_argument("--static-designs", type=int, default=60)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_image_pass.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    geom = cg.load("ep4cgx150")
    tiles = lab_tiles(geom)
    dec = rd.Decoder([a.tables])
    rng = random.Random(1)
    all_names = [n for n in cc.designs("gx150_sp_*") if not ccm.split_of(n, "even")]
    names = all_names[:a.corpus]
    # carry masks: most common masks among corpus arithmetic cells (sum_lutc_input = cin)
    cm = collections.Counter()
    for n in all_names[:40]:
        for at in cc.load_vo(n).atoms.values():
            if at["type"] == "cycloneive_lcell_comb" and at["params"].get("sum_lutc_input") == "cin":
                cm[int(at["params"]["lut_mask"].split("'h")[1], 16)] += 1
    carry_masks = {m for m, _c in cm.most_common(CARRY_TOP)}
    log.info("carry masks (top %d of corpus arithmetic cells): %s", CARRY_TOP, [f"{m:04x}" for m in carry_masks])

    img = cc.cram_plane(Path(a.image).read_bytes(), geom)
    log.info("image: %d set bits of %d x %d positions (%.2f%%)", len(img), *img.shape,
             100 * len(img) / (img.shape[0] * img.shape[1]))
    subjects = [("image", img), ("control", shuffle_control(img, 7))]
    for n in names:
        subjects.append((n, cc.load(n)["plane"]))
    io_sigs = load_io_sigs()
    stat = static_bits(cc.designs("gx150_sp_*")[:a.static_designs])
    log.info("static bits (set in >= %.0f%% of %d corpus designs): %d", 100 * STATIC_FRAC, a.static_designs, len(stat))
    for name, plane in subjects:
        log.info("=== %s", name)
        st, masks, used = lut_stats(name, plane, geom, tiles, carry_masks)
        act = active_tiles(used, tiles)
        log.info("[LAB] active LABs (a used LE): %d of %d", len(act), len(tiles))
        samp = rng.sample(act, min(SAMPLE_TILES, len(act))) if act else []
        cats, nread = route_classes(dec, plane, geom, samp, rng)
        nz = cats["known"] + cats["ambiguous"] + cats["unknown"]
        log.info("[ROUTE] %s: %d active LABs sampled, %d muxes read: zero %d, known %d, ambiguous %d, "
                 "nonzero-unknown %d; unknown share of nonzero %.3f; nonzero per LAB %.1f",
                 name, len(samp), nread, cats["zero"], cats["known"], cats["ambiguous"], cats["unknown"],
                 cats["unknown"] / max(nz, 1), nz / max(len(samp), 1))
        res, why, drivers, fan = netlist_stats(dec, plane, geom, tiles, masks, rng)
        fh = collections.Counter(min(v, 9) for v in fan.values())
        tot_in = res["input_resolved"] + res["input_unresolved"]
        log.info("[NET] %s: dependent LE inputs traced %d: resolved to a unique driver %d (%.3f), unresolved %d %s; "
                 "driver kinds %s; nodes expanded %d; comb back-edges %d; fan-out of seen drivers (1..9+) %s", name, tot_in, res["input_resolved"],
                 res["input_resolved"] / max(tot_in, 1), res["input_unresolved"], dict(why.most_common(4)),
                 dict(drivers.most_common(4)), res["nodes_expanded"], res["comb_loops"],
                 [fh.get(i, 0) for i in range(1, 10)])
        n, edges, sites = io_stats(plane, io_sigs)
        log.info("[IO] %s: output sites with full signature %d, input sites %d; edges %s", name, n["IOOBUF"],
                 n["IOIBUF"], dict(edges))
        cl = claims(plane, geom, tiles, dec, io_sigs, stat)
        log.info("[CLAIM] %s: set bits %d: LUT %d, routing-mux positions %d, IO %d, static %d; claimed (union) "
                 "%d = %.3f, unclaimed %d = %.3f", name, cl["set_bits"], cl["lut"], cl["route"], cl["io"],
                 cl["static"], cl["claimed"], cl["claimed"] / max(cl["set_bits"], 1), cl["unclaimed"],
                 cl["unclaimed"] / max(cl["set_bits"], 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
