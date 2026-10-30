#!/usr/bin/env python3.15t
"""Survey of every MAC (block 41) asmdb group: bits set per corpus design (which groups the corpus ever exercises).  Log: tmp/logs/cycloneiv_clean_mac_survey.log

  python3.15t scripts/cycloneiv_clean_mac_survey.py [glob]       # default gxhb_mac*   -> tmp/logs/cycloneiv_clean_mac_survey.json
Per (group name, gi): cells per instance (all site-0 mux paths + aux), designs with any cell set in a used instance, designs in which the cells differ.
"""
import collections
import fnmatch
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import asmdb_walk as W, ddb, fields as F, ffctl, macctl, plane as P, tracer as T  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_mac_survey.log")


def main():
    pat = sys.argv[1] if len(sys.argv) > 1 else "gxhb_mac*"
    sys.path.insert(0, ddb.SCRIPTS)
    import cycloneiv_clean_dirt as D
    w = W.Walk()
    nm = D.enum_tables()
    flds = [f for f in F.fields(w, nm, block_types={41})]
    bs = F.bases(w, 41)
    tab = P.load_tables()
    mc = macctl.MacCtl(w)
    cols = {}
    for f in flds:
        offs = [o for site in f.sites[:1] for p in site for o in p.tolist()] + [o for a in f.aux for o in a.tolist()]
        c = ffctl._cols(bs, offs, tab)
        cols[(f.name, f.gi)] = (np.stack([c[i] for i in sorted(c)], axis=1) if c else None, len(offs))
    designs = sorted(d for d in os.listdir(os.path.join(REPO, "corpus", "cycloneiv")) if fnmatch.fnmatch(d, pat))
    res = collections.defaultdict(lambda: {"designs": [], "cells": 0})
    log = open(LOG, "w")
    for d in designs:
        rbf = os.path.join(REPO, "corpus", "cycloneiv", d, "bitstream.rbf")
        if not os.path.exists(rbf):
            continue
        bits = T.plane_bits(rbf)
        used = np.flatnonzero(mc.used(bits)).tolist()
        if not used:
            continue
        for key, (c, n) in cols.items():
            if c is None:
                continue
            res[key]["cells"] = c.shape[1]
            hit = [i for i in used if bits[c[i]].any()]
            if hit:
                res[key]["designs"].append(d)
        print(d, "used", used, file=log, flush=True)
    out = {f"{k[0]}#{k[1]}": v for k, v in sorted(res.items())}
    for f in flds:
        k = f"{f.name}#{f.gi}"
        out.setdefault(k, {"designs": [], "cells": 0})
    json.dump(out, open(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_mac_survey.json"), "w"), indent=0)
    by = collections.OrderedDict()
    for k, v in out.items():
        n, gi = k.rsplit("#", 1)
        e = by.setdefault(n, [0, 0])
        e[0] += 1
        e[1] += len(v["designs"]) > 0
    for n, (g, h) in by.items():
        print(f"{n:42s} groups {g:3d} exercised {h:3d}")


main()
