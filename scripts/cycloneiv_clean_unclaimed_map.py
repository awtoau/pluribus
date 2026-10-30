#!/usr/bin/env python3
"""Unclaimed CRAM bits by column kind / band after every vendor claim source, plus the new absolute-address groups (#169).

  python3.15t scripts/cycloneiv_clean_unclaimed_map.py     # log tmp/logs/cycloneiv_clean_unclaimed_map.log, json tmp/cycloneiv_clean/unclaimed_map.json

Claim sources (vendor only): asm.ddb routing, asmdb LAB / MEAB / MAC calc groups (fields.py), default-bit list, and the std / dumb
groups of every other block type (their mux bits are absolute addresses: calc groups alone carry a BLOCK_INFO, docs/cycloneiv-clean-hardblocks-reversing.md).
Regions: geometry file column kinds (FX = first frame of each column), tile rows v 23..6322, IO bands elsewhere.
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
from lifters.cycloneiv_clean import asmdb_walk as W, ddb, fields as F, plane as P  # noqa: E402
import cycloneiv_clean_dirt as D  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_unclaimed_map.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "unclaimed_map.json")
GEOM = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_geom.json")


def group_bits(w, g):
    """all mux bit values of one group (std / stlmap: path muxes, dumb: bit list), raw as stored."""
    if g["cls"] == 7:
        return list(g["bits"])
    out = []
    for p in g["paths"]:
        for r in p:
            if r:
                out += w.mux(r)["bits"]
    return out


def absolute_masks(w):
    """per block type: CRAM mask of the absolute-address (tag 0) bits of its std / dumb / stlmap groups (no BLOCK_INFO)."""
    out = collections.OrderedDict()
    for g in w.groups():
        if g["cls"] == 5:
            continue
        m = out.setdefault(g["btype"], np.zeros(P.N_BITS, bool))
        a = np.array(group_bits(w, g), np.int64)
        a = a[(a >= 0) & (a < P.N_BITS)]
        m[a] = True
    return out


def claimed_mask(log=None):
    """-> (claimed bool[N_BITS], w, names): asm.ddb + default list + LAB / MEAB / MAC calc groups (fields.py)."""
    w = W.Walk()
    names = D.enum_tables()
    flds = F.fields(w, names)
    a = np.asarray(ddb.Asm().pos, np.int64) & ddb.ADDR_MASK
    asm = np.zeros(P.N_BITS, bool)
    asm[a[a < P.N_BITS]] = True
    dflt = np.array([x for x in w.default_bits if x < 0x80000000], np.int64)
    claimed = asm.copy()
    claimed[dflt] = True
    for bt in F.PLACED:
        m = F.claim_masks(w, flds, bt)
        claimed |= m["path"] | m["aux"]
    return claimed, w, names


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    log = logging.getLogger("unc")
    log.setLevel(logging.INFO)
    log.addHandler(logging.FileHandler(LOG, "w"))
    log.addHandler(logging.StreamHandler(sys.stdout))
    claimed, w, names = claimed_mask()
    base = int(claimed.sum())
    log.info("claimed (asm.ddb + default + LAB/MEAB/MAC) %d, unclaimed %d", base, P.N_BITS - base)
    res = {"base_claimed": base, "abs_blocks": {}}
    for bt, m in absolute_masks(w).items():
        nm = names["block_type"].get(bt, str(bt))
        res["abs_blocks"][nm] = dict(bits=int(m.sum()), new=int((m & ~claimed).sum()))
        log.info("abs-address groups %s: %d CRAM bits, %d new", nm, m.sum(), (m & ~claimed).sum())
        claimed |= m
    res["claimed_total"] = int(claimed.sum())
    res["unclaimed_total"] = int(P.N_BITS - claimed.sum())
    log.info("claimed %d unclaimed %d", res["claimed_total"], res["unclaimed_total"])
    g = json.load(open(GEOM))
    fx = np.array([g["FX"][str(i)] for i in range(len(g["FX"]))], np.int64)
    kinds = [g["col_kind"][str(i)] for i in range(len(g["FX"]))]
    s = np.arange(P.N_BITS, dtype=np.int64) % P.FRAMES
    v = np.arange(P.N_BITS, dtype=np.int64) // P.FRAMES
    col = np.searchsorted(fx, s, side="right") - 1          # column of each frame; frames before FX[0] -> -1
    band = np.where((v >= 23) & (v <= 6322), "tile", "io_band")
    kcol = np.array(kinds + ["pre"])[col]
    tab = collections.OrderedDict()
    unc = ~claimed
    for k in ("pre", "IOL", "LAB", "M9K", "MUL", "IOR"):
        for b in ("tile", "io_band"):
            sel = (kcol == k) & (band == b)
            tab[f"{k}:{b}"] = dict(total=int(sel.sum()), unclaimed=int((sel & unc).sum()))
            log.info("%-12s total %10d unclaimed %10d", f"{k}:{b}", sel.sum(), (sel & unc).sum())
    res["regions"] = tab
    # unclaimed tile bits by v mod 70 (one tile row = 70 v) in LAB / M9K columns: which in-tile rows stay free
    for k in ("LAB", "M9K"):
        sel = (kcol == k) & (band == "tile") & unc
        h = np.bincount((v[sel] - 23) % 70, minlength=70)
        res[f"{k}_unclaimed_by_vmod70"] = h.tolist()
        log.info("%s unclaimed by (v-23) mod 70: %s", k, h.tolist())
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
