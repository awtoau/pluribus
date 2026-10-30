#!/usr/bin/env python3.15t
"""Bit sets of the Cyclone IV GX clean-decoder inventory classes, as rbf-plane cells (flat = frame * NV + v).  Vendor-derived only (#169).

  python3.15t scripts/cycloneiv_clean_classes.py     # counts per class -> tmp/logs/cycloneiv_clean_classes.log

Library use: scripts/cycloneiv_bit_inventory.py (class partition).  Every set is vendor group bits (asmdb walk, asm.ddb, CFF table); the
only evidence-dependent set is 9a (CFF bits a pair build toggled inside the field's group).  Tiers are NOT decided here:
claims_register.py links evidence, provenance/tiering.py computes the tier.

Classes (claim order in the inventory = order below; each set is minus the sets before it):
  1a  LUT INIT              LAB LE_LUT_FUNCTION group bits
  8a  clock select          LAB LAB_CLOCK_FAST_MUX + LE_CLOCK_SELECT (path + aux)
  8b  register-used         LAB LE_REG_OUT_YGR + LE_USE_SYNC_CLEAR / LOAD
  8c  clock-network routing asm.ddb entries of records of the clock element types (CLKBUF_OUT ... BLK_CLK_BUF)
  8d  other LAB groups      every other LAB group bit
  8e  MEAB (M9K) groups     every MEAB group bit
  8f  MAC groups            every MAC group bit
  8g  routing               remaining asm.ddb entries + asmdb default-bit list (CRAM)
  9a  IO CFF measured       CFF bits of slew / pull-up / bus-hold / drive / standard groups a pair build toggled (+ open-drain flag)
  9b  IO CFF sampled-rule   the same five fields' group bits at the IO sites no pair build covered
  9c  IO CFF decoded        every other IO group CFF bit
  (IO block CRAM group offsets are relative: read as absolute they land in LAB columns, so no class is made of them)
"""
import collections
import json
import logging
import os
import sys

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import asmdb_walk as W, ddb, fields as F, cycloneiv_io as IO, names as N, plane as P  # noqa: E402

log = logging.getLogger("clean_classes")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_classes.log")
ORDER = ("1a", "8a", "8b", "8c", "8d", "8e", "8f", "8g", "9a", "9b", "9c")
CLOCK_SELECT_NAMES = ("LAB_CLOCK_FAST_MUX", "LE_CLOCK_SELECT")                      # source: lifters/cycloneiv_clean/clocks.py
REG_USED_NAMES = ("LE_REG_OUT_YGR", "LE_USE_SYNC_CLEAR", "LE_USE_SYNC_LOAD")        # source: lifters/cycloneiv_clean/reg_used.py
CLOCK_RECORD_TYPES = ("CLKBUF_OUT", "GLOBAL_CLK_H", "GLOBAL_CLK_V", "SCLK_TO_ROWCLK_BUF", "LAB_CLK", "BLK_CLK_BUF")   # source: clocks.py network
PAIR_FIELDS = ("standard", "drive", "slew", "pull-up", "bus-hold")   # io_decode.cross_check: fields with matched bits
IO_DECODE_JSON = os.path.join(REPO, "databases", "cycloneiv", "io_decode.json")


def plane_flat(addr, nv, vmap, tab):
    """sof data bit index -> rbf-plane flat cell (A4 + A5; periphery / CRAM frames share one file frame axis)."""
    addr = np.unique(np.asarray(addr, np.int64))
    addr = addr[(addr >= 0) & (addr < P.N_BITS)]
    r, j, k = P.sof_to_rbf(addr, tab)
    return P.plane_frame(r) * nv + vmap[j * 8 + k]


def cff_flat(cff, bits, nv, vmap):
    """CFF bit indices -> every rbf cell of those bits (4 replicas, 8 for 64 bits)."""
    bits = np.unique(np.asarray(bits, np.int64))
    n = cff.count[bits]
    row = np.repeat(cff.first[bits], n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
    c = cff.cells[row]
    if (c[:, 0] < 1).any():
        raise ValueError("CFF cell in frame 0")
    return np.unique(c[:, 0].astype(np.int64) * nv + vmap[c[:, 1].astype(np.int64) * 8 + c[:, 2]])


def fabric(w, names_):
    """{class: sof addresses} of the LAB / MEAB / MAC asmdb groups."""
    flds = F.fields(w, names_)
    bs = {bt: F.bases(w, bt) for bt in F.PLACED}
    out = collections.defaultdict(list)
    for f in flds:
        if f.btype not in F.PLACED:
            continue
        if f.btype == 18:
            cid = ("1a" if f.name == "LE_LUT_FUNCTION" else "8a" if f.name.startswith(CLOCK_SELECT_NAMES)
                   else "8b" if f.name.startswith(REG_USED_NAMES) else "8d")
        else:
            cid = "8e" if f.btype == 39 else "8f"
        for site in f.sites:
            for off in site:
                out[cid].append(F.absolute(bs[f.btype], off).ravel())
        for off in f.aux:
            if cid != "1a":
                out[cid].append(F.absolute(bs[f.btype], off).ravel())
    return {k: np.unique(np.concatenate(v)) for k, v in out.items()}


def routing(w):
    """({clock-network, other} asm.ddb addresses, default-list CRAM bits)."""
    asm, rt = ddb.Asm(), ddb.Routing()
    a = np.asarray(asm.pos, np.int64) & ddb.ADDR_MASK
    t = np.maximum(rt.tpl, 0)
    rec_enum = np.where(rt.tpl >= 0, rt.enum[t].astype(np.int64), -1)
    clk = np.isin(rec_enum, [N.enum_of(n) for n in CLOCK_RECORD_TYPES])
    in_clk = clk[np.asarray(asm.rec, np.int64)]
    ok = a < P.N_BITS
    dflt = np.array([b for b in w.default_bits if b < P.N_BITS], np.int64)
    return np.unique(a[ok & in_clk]), np.unique(a[ok & ~in_clk]), np.unique(dflt), int(clk.sum())


def io_sets(chain, pairs):
    """-> dict(measured=set((btype,site), bit), tested sites, rank, per-field evidence rows, all CFF / CRAM bits)."""
    import lifters.cycloneiv_clean.io_decode as D
    own_sites = {s for s, g in chain.cff.items() if D.ANCHOR_GROUP in g}
    ranked = sorted(own_sites, key=chain.anchor)
    rank = {s: i for i, s in enumerate(ranked)}
    b_by = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in D._rows(pairs):
        s = chain.ball_site.get(r["pin"])
        if s is not None and r["setting"] in PAIR_FIELDS:
            b_by[r["setting"]][r["pin"]].update(r["cff"])
    measured, rows = set(), []
    for field in PAIR_FIELDS:
        for pin, B in sorted(b_by[field].items()):
            s = chain.ball_site[pin]
            A = {b for n in D.FIELD_GROUPS[field] for b in chain.cff[s].get(n, [])}
            hit = sorted(B & A)
            if hit:
                measured.update(hit)
                rows.append(dict(field=field, pin=pin, site=list(s), rank=rank[s], matched=len(hit), group_bits=len(A), bits=hit))
    od = json.load(open(IO_DECODE_JSON))["open_drain"]
    od_bits = []
    for e in od:
        for b in e["diff"]:
            od_bits.append(int(b))
            rows.append(dict(field="open-drain", pin=e["pin"], site=e["site"], rank=None, matched=1, group_bits=1, bits=[int(b)]))
    measured.update(od_bits)
    field_bits = {f: {b for s in own_sites for n in D.FIELD_GROUPS[f] for b in chain.cff[s].get(n, [])} for f in PAIR_FIELDS}
    tested = {chain.ball_site[p] for f in PAIR_FIELDS for p in b_by[f] if p in chain.ball_site}
    all_cff = {b for g in chain.cff.values() for bs in g.values() for b in bs}
    cram = [a for g in chain.cram.values() for bs in g.values() for a in bs]
    sites_other = {s for s in chain.cff if s not in tested}
    other_field_bits = {b for s in sites_other for f in PAIR_FIELDS for n in D.FIELD_GROUPS[f] for b in chain.cff[s].get(n, [])}
    return dict(measured=measured, rows=rows, n_sites=len(ranked), tested=sorted(tested), rank=rank, field_bits=field_bits,
                other_field_bits=other_field_bits, all_cff=all_cff, cram=np.array(cram, np.int64), od_bits=od_bits)


def build(nv, vmap, tab=None):
    """-> ({class: flat plane cells}, meta).  Sets are disjoint (each minus the earlier ones)."""
    import cycloneiv_clean_dirt as CD
    import lifters.cycloneiv_clean.io_decode as D
    tab = tab or P.load_tables()
    w = W.Walk()
    names_ = CD.enum_tables()
    fab = fabric(w, names_)
    clk, rest, dflt, n_clk_rec = routing(w)
    sof = {k: v for k, v in fab.items()}
    sof["8c"], sof["8g"] = clk, np.union1d(rest, dflt)
    out, seen, meta = {}, np.zeros(0, np.int64), {"clock_records": n_clk_rec, "sof_bits": {}}
    for cid in ORDER[:8]:
        a = plane_flat(sof[cid], nv, vmap, tab)
        meta["sof_bits"][cid] = int(len(sof[cid]))
        out[cid] = np.setdiff1d(a, seen, assume_unique=True)
        seen = np.union1d(seen, a)
        log.info("%-3s sof bits %10d  plane cells %10d  new %10d", cid, len(sof[cid]), len(a), len(out[cid]))
    chain, pairs = D.Chain(), IO.io_pairs()
    io = io_sets(chain, pairs)
    cff = IO.Cff()
    m = np.array(sorted(io["measured"]), np.int64)
    nine_b = np.array(sorted(io["other_field_bits"] - io["measured"]), np.int64)
    rest_cff = np.array(sorted(io["all_cff"] - io["measured"] - io["other_field_bits"]), np.int64)
    sets = {"9a": cff_flat(cff, m, nv, vmap), "9b": cff_flat(cff, nine_b, nv, vmap), "9c": cff_flat(cff, rest_cff, nv, vmap)}
    meta["cff_bits"] = {"9a": int(len(m)), "9b": int(len(nine_b)), "9c": int(len(rest_cff))}
    for cid in ORDER[8:]:
        out[cid] = np.setdiff1d(sets[cid], seen, assume_unique=True)
        seen = np.union1d(seen, sets[cid])
        log.info("%-3s plane cells %10d  new %10d", cid, len(sets[cid]), len(out[cid]))
    meta["io"] = {k: io[k] for k in ("n_sites", "tested", "rows", "od_bits")}
    meta["io"]["rank"] = {f"{k[0]}:{k[1]}": v for k, v in io["rank"].items()}
    return out, meta


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG, "w")])
    import cycloneiv_corpus as cc
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of("EP4CGX150"))
    vmap = cc.vmap_for(P.RBF_FRAME_BYTES, tuple(g.lane_bytes), tuple(map(tuple, g.lane_swaps)))
    out, meta = build(len(vmap), vmap)
    for k, v in out.items():
        log.info("class %s: %d plane cells", k, len(v))
    log.info("meta %s", json.dumps({k: v for k, v in meta.items() if k != "io"}))


if __name__ == "__main__":
    main()
