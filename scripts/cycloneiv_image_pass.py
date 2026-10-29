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
  2 routing, 3 netlist   removed with the learned-table decoder; pending the clean P2 tracer (#165)
  4 IO           sites whose configuration signature (cycloneiv_io_bits.py) is fully set
  5 claims       set bits explained by the decode (LUT-mask bits, IO signatures,
                 bits set in >= STATIC_FRAC of the corpus) vs unclaimed

  python3.15t scripts/cycloneiv_image_pass.py --image PATH
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
import cycloneiv_common as ccm  # noqa: E402

log = logging.getLogger("cycloneiv_image_pass")
STATIC_FRAC = 0.95      # a bit set in this fraction of corpus designs is static configuration
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


def claims(plane, geom, tiles, io_sigs, static_keys):
    """set bits explained by: LUT-mask + used bit, IO signatures, static bits.  -> dict of counts.
    Routing-mux positions are pending the clean P2 tracer (#165)."""
    keys = plane.keys
    nf, nv = plane.shape
    hit = {"lut": np.zeros(len(keys), dtype=bool), "io": np.zeros(len(keys), dtype=bool), "static": np.zeros(len(keys), dtype=bool)}

    def flag(name, k):
        k = np.unique(k[(k >= 0)])
        i = np.searchsorted(keys, k)
        i = np.minimum(i, len(keys) - 1)
        ok = keys[i] == k
        hit[name][i[ok]] = True
    for df, dv in ll.DK + [(-8, -1)]:
        f, v = le_positions(geom, tiles, df, dv)
        flag("lut", f * nv + v)
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
        log.info("[ROUTE]/[NET] pending clean P2 tracer (#165)")
        n, edges, sites = io_stats(plane, io_sigs)
        log.info("[IO] %s: output sites with full signature %d, input sites %d; edges %s", name, n["IOOBUF"],
                 n["IOIBUF"], dict(edges))
        cl = claims(plane, geom, tiles, io_sigs, stat)
        log.info("[CLAIM] %s: set bits %d: LUT %d, IO %d, static %d; claimed (union) "
                 "%d = %.3f, unclaimed %d = %.3f", name, cl["set_bits"], cl["lut"], cl["io"],
                 cl["static"], cl["claimed"], cl["claimed"] / max(cl["set_bits"], 1), cl["unclaimed"],
                 cl["unclaimed"] / max(cl["set_bits"], 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
