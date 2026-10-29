#!/usr/bin/env python3
"""Per block type: groups / muxes / absolute CRAM bits claimed by the vendor asmdb, and what stays unclaimed (#169).

  python3.15t scripts/cycloneiv_clean_fields_coverage.py      # log tmp/logs/cycloneiv_clean_fields_coverage.log, json tmp/cycloneiv_clean/fields_coverage.json

Claim sources (vendor only): asm.ddb routing addresses, asmdb LUT / LAB / MEAB / MAC group bits (fields.py), asmdb default-bit list.
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

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_fields_coverage.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "fields_coverage.json")


def asm_mask():
    a = np.asarray(ddb.Asm().pos, np.int64) & ddb.ADDR_MASK
    m = np.zeros(P.N_BITS, bool)
    m[a[a < P.N_BITS]] = True
    return m


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    log = logging.getLogger("cov")
    log.setLevel(logging.INFO)
    log.addHandler(logging.FileHandler(LOG, "w"))
    log.addHandler(logging.StreamHandler(sys.stdout))
    w = W.Walk()
    names = D.enum_tables()
    flds = F.fields(w, names)
    res = {"blocks": {}, "N_BITS": P.N_BITS}
    # raw per block type (all 4,664-name groups)
    per = collections.OrderedDict()
    for f in flds:
        e = per.setdefault(f.block, dict(btype=f.btype, groups=0, std=0, calc=0, dumb=0, stlmap=0, offsets=0, placed=f.btype in F.PLACED))
        e["groups"] += 1
        e[f.cls] += 1
        e["offsets"] += sum(len(o) for s in f.sites for o in s)
    asm = asm_mask()
    dflt = np.array([a for a in w.default_bits if a < 0x80000000], np.int64)
    dmask = np.zeros(P.N_BITS, bool)
    dmask[dflt] = True
    union = asm | dmask
    log.info("asm.ddb %d, default list CRAM %d, union %d", asm.sum(), dmask.sum(), union.sum())
    lut = np.zeros(P.N_BITS, bool)
    for f in flds:
        if f.name == "LE_LUT_FUNCTION":
            for site in f.sites:
                for off in site:
                    lut[F.absolute(F.bases(w, f.btype), off).ravel()] = True
    log.info("LE_LUT_FUNCTION absolute bits %d, overlap asm.ddb %d", lut.sum(), (lut & asm).sum())
    total = union | lut
    for bt, name in F.PLACED.items():
        m = F.claim_masks(w, flds, bt)
        both = m["path"] | m["aux"]
        e = per[name]
        bs = F.bases(w, bt)
        # sof frame extent of the block's columns (claim extent, from the claims only)
        fr = np.nonzero(both)[0] % P.FRAMES
        e.update(instances=int(len(bs)), path_bits=int(m["path"].sum()), aux_bits=int(m["aux"].sum()), claimed_bits=int(both.sum()),
                 in_asm_ddb=int((both & asm).sum()), new_vs_asm_ddb=int((both & ~asm).sum()), in_default_list=int((both & dmask).sum()),
                 frame_min=int(fr.min()), frame_max=int(fr.max()))
        log.info("%s: %s", name, json.dumps(e))
        total |= both
    res["claimed_total"] = int(total.sum())
    res["unclaimed_total"] = int(P.N_BITS - total.sum())
    # per-block-type claimed-by-vendor-group (new = not asm.ddb, not default), split by role for placed types
    roles = collections.OrderedDict()
    for bt, name in F.PLACED.items():
        bs = F.bases(w, bt)
        for f in flds:
            if f.btype != bt:
                continue
            r = roles.setdefault((name, f.role), [np.zeros(P.N_BITS, bool), 0])
            for site in f.sites:
                for off in site:
                    r[0][F.absolute(bs, off).ravel()] = True
            r[1] += 1
    res["roles"] = {f"{k[0]}:{k[1]}": dict(groups=v[1], bits=int(v[0].sum()), in_asm_ddb=int((v[0] & asm).sum())) for k, v in roles.items()}
    for k, v in res["roles"].items():
        log.info("role %s %s", k, json.dumps(v))
    res["blocks"] = per
    # extent regions: bits in the frame extent of each placed block's columns that no source claims
    ext = {}
    for bt, name in F.PLACED.items():
        e = per[name]
        sel = np.zeros(P.N_BITS, bool)
        s = np.arange(P.N_BITS, dtype=np.int64) % P.FRAMES
        sel = (s >= e["frame_min"]) & (s <= e["frame_max"])
        ext[name] = dict(frames=e["frame_max"] - e["frame_min"] + 1, bits=int(sel.sum()), unclaimed=int((sel & ~total).sum()))
    res["frame_extent_unclaimed"] = ext
    for k, v in per.items():
        log.info("block %s %s", k, json.dumps(v))
    log.info("claimed %d unclaimed %d of %d", res["claimed_total"], res["unclaimed_total"], P.N_BITS)
    log.info("extent %s", json.dumps(ext))
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1, default=int)
    return 0


if __name__ == "__main__":
    sys.exit(main())
