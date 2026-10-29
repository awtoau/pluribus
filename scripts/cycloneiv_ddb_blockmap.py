#!/usr/bin/env python3.15t
"""Exact asm group <-> routing.ddb graph-edge correspondence and block -> output-wire map (#141).

Correspondence: group k of source record r (asm order) == fan-out edge k of r (template order);
dest = V(r) + offs[k].  The last (ng - ne) groups of a record are select-bit pseudo-groups
(no edge).  A block (mux) must map to ONE destination wire: that is the self-check.

  python3.15t scripts/cycloneiv_ddb_blockmap.py build      # -> tmp/ddb/<die>_blockmap.npz + report
Log tmp/logs/cycloneiv_ddb_blockmap.log.
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_ddb_asm as A  # noqa: E402

log = logging.getLogger("cycloneiv_ddb_blockmap")
DIE = "stingray4"
T = os.path.join(A.TMP, f"{DIE}_dec_")


def group_edges():
    """-> dict of per-group arrays: grec, k (index within record), real (has edge), dest (-1 if pseudo)."""
    grec = np.load(T + "grec.npy")
    z = np.load(os.path.join(A.TMP, f"{DIE}_rt_fanout.npz"))
    V, tpl, cnt, eoff, offs = z["V"].astype(np.int64), z["tpl"], z["cnt"], z["eoff"], z["offs"].astype(np.int64)
    n = len(V)
    ng = np.bincount(grec, minlength=n)
    gfirst = np.concatenate([[0], np.cumsum(ng)[:-1]])
    k = np.arange(len(grec)) - gfirst[grec]
    ne = cnt[tpl].astype(np.int64)
    if (ng < ne).any():
        raise SystemExit(f"{int((ng < ne).sum())} records with fewer asm groups than graph edges")
    real = k < ne[grec]
    pick = np.minimum(eoff[tpl[grec]] + k, len(offs) - 1)
    dest = np.where(real, V[grec] + offs[pick], -1)
    return dict(grec=grec, k=k, real=real, dest=dest, ng=ng, ne=ne, n=n)


def build():
    ge = group_edges()
    block = np.load(T + "block.npy")
    gsize = np.load(T + "gsize.npy")
    real, dest = ge["real"], ge["dest"]
    bi = np.flatnonzero(real)
    b, d = block[bi], dest[bi]
    o = np.argsort(b, kind="stable")
    b, d, bi = b[o], d[o], bi[o]
    st = np.flatnonzero(np.r_[True, b[1:] != b[:-1]])
    en = np.r_[st[1:], len(b)]
    dmin = np.minimum.reduceat(d, st)
    dmax = np.maximum.reduceat(d, st)
    nb = len(st)
    one = dmin == dmax
    log.info("real groups %d / %d (pseudo %d); blocks with >=1 real group %d; single-destination blocks %d (%.4f%%)",
             int(real.sum()), len(real), int((~real).sum()), nb, int(one.sum()), 100.0 * one.sum() / nb)
    # multi-destination blocks: distinct dest count histogram + by source record family
    multi = np.flatnonzero(~one)
    hist = collections.Counter()
    for i in multi[:200000].tolist():
        hist[len(np.unique(d[st[i]:en[i]]))] += 1
    log.info("multi-destination blocks %d; distinct-dest histogram (first 200k) %s", len(multi), dict(hist))
    # block -> dest (single) and the sources feeding it
    out = os.path.join(A.TMP, f"{DIE}_blockmap.npz")
    np.savez(out, block=b[st], dest=dmin, single=one, gfirst=st, gend=en, gidx=bi, gdest=d)
    log.info("wrote %s", out)


if __name__ == "__main__":
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_ddb_blockmap.log"))])
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    {"build": build}[cmd]()
