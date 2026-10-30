#!/usr/bin/env python3
"""What the unclaimed CRAM residue is: per-region ever-set statistics over the held GX150 corpus, tile-local clustering (#169).

  python3.15t scripts/cycloneiv_clean_residue.py [ever_set.npy]    # log tmp/logs/cycloneiv_clean_residue.log, json tmp/cycloneiv_clean/residue.json

- Claims = scripts/cycloneiv_clean_unclaimed_map.claimed_mask() + ASMDB_DEFAULT_BIT_CALC objects (bit x every instance of its BLOCK_INFO).
- ever_set bitmap (scripts/cycloneiv_ever_set.py, packed bits, rbf plane cell = file frame * NV + v) is mapped through plane_flat (A4 + A5).
- Tile-local cell = (frame - FX[column], (v - 23) mod 70) per column kind; a local cell is "never" when no instance of that column kind sets it.
"""
import json
import logging
import os
import sys

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import fields as F, plane as P  # noqa: E402
import cycloneiv_clean_unclaimed_map as U  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_residue.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "residue.json")
EVER = os.path.join(REPO, "databases", "cycloneiv", "ever_set.npy")
GEOM = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_geom.json")
CHUNK = 4_000_000


def dbc_mask(w):
    """ASMDB_DEFAULT_BIT_CALC (class 11): `bit` at every instance of its BLOCK_INFO, bit relative like a group offset."""
    m = np.zeros(P.N_BITS, bool)
    bis = w.block_infos()
    for o in w.S["DG"].objs[1:]:
        if o["cls"] == 11:
            bt = bis[o["bi"][1] - 1]["btype"]
            if bt in F.PLACED:
                m[F.absolute(F.bases(w, bt), [o["bit"]]).ravel()] = True
    return m


def plane_flat_ordered(addr, nv, vmap, tab):
    """sof data bit index -> rbf-plane flat cell (A4 + A5), order preserved."""
    r, j, k = P.sof_to_rbf(addr, tab)
    return P.plane_frame(r) * nv + vmap[j * 8 + k]


def main():
    import logging as lg_
    log = lg_.getLogger("res")
    log.setLevel(logging.INFO)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    log.addHandler(lg_.FileHandler(LOG, "w"))
    log.addHandler(lg_.StreamHandler(sys.stdout))
    ever_path = sys.argv[1] if len(sys.argv) > 1 else EVER
    claimed, w, names = U.claimed_mask()
    d = dbc_mask(w)
    log.info("DEFAULT_BIT_CALC bits %d, new vs claimed %d", d.sum(), (d & ~claimed).sum())
    claimed |= d
    res = {"dbc_new": int((d & ~claimed).sum())}
    g = json.load(open(GEOM))
    fx = np.array([g["FX"][str(i)] for i in range(len(g["FX"]))], np.int64)
    kinds = np.array([g["col_kind"][str(i)] for i in range(len(fx))] + ["pre"])
    N = P.N_BITS
    s = np.arange(N, dtype=np.int64) % P.FRAMES
    v = np.arange(N, dtype=np.int64) // P.FRAMES
    col = np.searchsorted(fx, s, side="right") - 1
    kcol = kinds[col]
    tile = (v >= 23) & (v <= 6322)
    unc = ~claimed
    ever_packed = np.load(ever_path)
    ever = np.unpackbits(ever_packed)[:6191 * 6368].astype(bool)
    import cycloneiv_geom as cg
    geo = cg.load(cg.die_of("EP4CGX150"))
    vmap = cc.vmap_for(P.RBF_FRAME_BYTES, tuple(geo.lane_bytes), tuple(map(tuple, geo.lane_swaps)))
    nv = len(vmap)
    tab = P.load_tables()
    flat = np.empty(N, np.int64)
    for a in range(0, N, CHUNK):
        flat[a:a + CHUNK] = plane_flat_ordered(np.arange(a, min(N, a + CHUNK), dtype=np.int64), nv, vmap, tab)
    st = ever[flat]
    log.info("ever-set designs bitmap: %d of %d plane cells set; claimed bits set %d / %d", ever.sum(), ever.size, (st & claimed).sum(), claimed.sum())
    res["claimed_set_frac"] = float((st & claimed).sum() / claimed.sum())
    tab_out = {}
    for k in ("LAB", "M9K", "MUL", "IOL", "IOR", "pre"):
        for name, sel in (("tile", tile), ("band", ~tile)):
            m = (kcol == k) & sel & unc
            if m.sum():
                tab_out[f"{k}:{name}"] = dict(residue=int(m.sum()), ever_set=int((m & st).sum()), never=int((m & ~st).sum()))
                log.info("%-10s residue %10d ever-set %10d never %10d", f"{k}:{name}", m.sum(), (m & st).sum(), (m & ~st).sum())
    res["regions"] = tab_out
    # tile-local clustering of residue bits per column kind
    loc_f = s - fx[col]
    loc_v = (v - 23) % 70
    for k in ("LAB", "M9K"):
        m = (kcol == k) & tile
        W_ = int(loc_f[m].max()) + 1
        idx = (loc_f[m] * 70 + loc_v[m])
        shape = W_ * 70
        tot = np.bincount(idx, minlength=shape)
        r = np.bincount(idx[unc[m]], minlength=shape)
        rs = np.bincount(idx[unc[m] & st[m]], minlength=shape)
        cl = np.bincount(idx[~unc[m]], minlength=shape)
        # local cell classes: fully claimed / fully residue-never / residue sometimes set / mixed claimed+residue
        pure_claim = int(((r == 0) & (tot > 0)).sum())
        pure_res_never = int(((cl == 0) & (rs == 0) & (r > 0)).sum())
        pure_res_set = int(((cl == 0) & (rs > 0)).sum())
        mixed = int(((cl > 0) & (r > 0)).sum())
        res[f"{k}_local"] = dict(local_cells=int((tot > 0).sum()), fully_claimed=pure_claim, residue_never_set=pure_res_never,
                                 residue_sometimes_set=pure_res_set, mixed_claimed_and_residue=mixed, width=W_)
        log.info("%s tile-local cells %d: fully claimed %d, residue never set %d, residue set in some build %d, mixed %d", k,
                 (tot > 0).sum(), pure_claim, pure_res_never, pure_res_set, mixed)
        np.savez_compressed(os.path.join(os.path.dirname(OUT), f"residue_{k}_local.npz"), tot=tot, residue=r, residue_set=rs, claimed=cl, width=W_)
    # partition of the LAB / M9K / MUL column tiles by claim source (first match wins), plus ever-set of each part
    from lifters.cycloneiv_clean import ddb  # noqa: E402
    flds = F.fields(w, names)
    a = np.asarray(ddb.Asm().pos, np.int64) & ddb.ADDR_MASK
    asm = np.zeros(N, bool)
    asm[a[a < N]] = True
    parts = {}
    for bt, nm_ in F.PLACED.items():
        bs = F.bases(w, bt)
        init = np.zeros(N, bool)
        other = np.zeros(N, bool)
        for f in flds:
            if f.btype != bt:
                continue
            tgt = init if f.role in ("lut_init", "ram_init") else other
            for site in f.sites:
                for off in site:
                    tgt[F.absolute(bs, off).ravel()] = True
            for off in f.aux:
                other[F.absolute(bs, off).ravel()] = True
        parts[nm_] = (init, other)
    out = {}
    for kind, nm_ in (("LAB", "LAB"), ("M9K", "MEAB"), ("MUL", "MAC")):
        init, other = parts[nm_]
        sel = (kcol == kind) & tile
        left = sel.copy()
        rows = []
        for label, m in (("content/LUT INIT group", init), ("other calc groups", other & ~init), ("asm.ddb routing only", asm & ~init & ~other),
                         ("default list / DEFAULT_BIT_CALC only", claimed & ~asm & ~init & ~other)):
            mm = left & m
            rows.append((label, int(mm.sum()), int((mm & st).sum())))
            left &= ~m
        rows.append(("residue (no record)", int(left.sum()), int((left & st).sum())))
        out[kind] = rows
        for r in rows:
            log.info("%s tile %-38s bits %10d ever-set %10d", kind, *r)
    res["tile_partition"] = out
    json.dump(res, open(OUT, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
