#!/usr/bin/env python3.15t
"""Pair diffs of the gxhb_macx_* / gxhb_mac_two_* specimens: changed cells per MAC group (block 41) of the used tile, plus total changed CRAM cells.

  python3.15t scripts/cycloneiv_clean_macx_diff.py        log tmp/logs/cycloneiv_clean_macx_diff.log, tmp/logs/cycloneiv_clean_macx_diff.json
"""
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import asmdb_walk as W, ddb, fields as F, ffctl, macctl, plane as P, tracer as T  # noqa: E402

sys.path.insert(0, ddb.SCRIPTS)
PAIRS = [("base0", "clkinv"), ("base0", "ena"), ("ena", "enainv"), ("base0", "aclr"), ("aclr", "aclrinv"), ("aclr", "aclrglob"), ("dynsab", "sregab"),
         ("dynsab", "sregb"), ("plain", "invda"), ("plain", "invdb")]
PAIRS = [(f"gxhb_macx_{a}", f"gxhb_macx_{b}") for a, b in PAIRS] + [("gxhb_mac_two_mult_w9", f"gxhb_mac_two_{n}") for n in ("out_reg", "in_reg", "mult_reg")]


def main():
    import cycloneiv_clean_dirt as D
    w = W.Walk()
    nm = D.enum_tables()
    flds = F.fields(w, nm, block_types={41})
    bs = F.bases(w, 41)
    tab = P.load_tables()
    cols = {}
    for f in flds:
        offs = [o for site in f.sites[:1] for p in site for o in p.tolist()] + [o for a in f.aux for o in a.tolist()]
        c = ffctl._cols(bs, offs, tab)
        cols[(f.name, f.gi)] = (sorted(c), np.stack([c[i] for i in sorted(c)], axis=1)) if c else None
    mc = macctl.MacCtl(w)
    out = {}
    for a, b in PAIRS:
        pa = T.plane_bits(os.path.join(REPO, "corpus", "cycloneiv", a, "bitstream.rbf"))
        pb = T.plane_bits(os.path.join(REPO, "corpus", "cycloneiv", b, "bitstream.rbf"))
        diff = pa != pb
        ia, ib = np.flatnonzero(mc.used(pa)), np.flatnonzero(mc.used(pb))
        r = {"changed_cells": int(diff.sum()), "used_a": ia.tolist(), "used_b": ib.tolist(), "groups": {}}
        for i in sorted(set(ia.tolist()) | set(ib.tolist())):
            for (n, gi), v in cols.items():
                if v is None:
                    continue
                pos, c = v
                ch = [(p, int(pa[c[i, k]]), int(pb[c[i, k]])) for k, p in enumerate(pos) if diff[c[i, k]]]
                if ch:
                    r["groups"][f"{i}:{n}#{gi}"] = ch
        out[f"{a} -> {b}"] = r
        print(a, "->", b, "changed", r["changed_cells"], "used", r["used_a"], r["used_b"])
        for k, v in r["groups"].items():
            print("   ", k, v)
    json.dump(out, open(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_macx_diff.json"), "w"), indent=0)


main()
