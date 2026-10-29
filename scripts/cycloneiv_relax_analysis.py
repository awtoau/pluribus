#!/usr/bin/env python3.15t
"""Cyclone IV #141 track 2: are the extra set bits of refused "full-pred-set" groups explained?

PREDICTION (stated before the run, 2026-10-29): in a block where a group has all its predicted
bits set but the block has 1-3 extra set bits, the extras are predicted bits of OTHER groups of
the same block that feed the SAME destination mux (routing.ddb fan-out: group k of record r =
edge k, dest = V(r)+offs[k]), i.e. shared second-level select bits.  Expected: >= 80 % of the
refused groups have all extras of that kind, and in >= 80 % of those the refused group is the
only fully-set group of its (block, dest) (a legal one-input-selected configuration).

Per refused group (npred>0, all pred set, bset[block] > npred) the extras are classified:
  S  predicted bit of another group of the same block with the SAME dest record
  O  predicted bit of another group of the block, different dest
  N  bit no group of the block predicts (second-level only)
Legal = refused group is the only fully-set group on its (block, dest).

  python3.15t scripts/cycloneiv_relax_analysis.py --image <bin|rbf>
Log tmp/logs/cycloneiv_relax_analysis.log
"""
import argparse
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_asm_decode as ad  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402

log = logging.getLogger("cycloneiv_relax_analysis")


def analyse(plane, dec, gdest, out=None):
    """-> dict of counts.  gdest: dest record per group (-1 = pseudo / none)."""
    ng = len(dec.gsize)
    gid = np.asarray(dec.gid)
    pred = np.asarray(dec.pred)
    block = np.asarray(dec.block)
    s = np.flatnonzero(plane.dense()[dec._flat(plane)])
    sp = s[pred[s]]
    nsp = np.bincount(gid[sp], minlength=ng).astype(np.int32)
    uk = np.unique(dec.e_ukey[s])
    bset = np.bincount(dec.ukey_block[uk], minlength=dec.nblocks).astype(np.int32)
    full = (dec.npred > 0) & (nsp == dec.npred)
    fired = full & (bset[block] == dec.npred)
    refused = full & (bset[block] > dec.npred)
    R = np.flatnonzero(refused)
    log.info("full-pred groups %d, fired %d, refused %d (blocks %d)", full.sum(), fired.sum(), len(R), len(np.unique(block[R])))
    # per (block, dest) number of fully-set groups
    N = int(gdest.max()) + 1
    F = np.flatnonzero(full)
    key = block[F].astype(np.int64) * (N + 1) + (gdest[F] + 1)
    kk, kc = np.unique(key, return_counts=True)
    # ukey -> predicting groups (restricted to refused blocks): sets of (dest) per ukey, per block
    rblk = np.zeros(dec.nblocks, bool)
    rblk[block[R]] = True
    ent = np.flatnonzero(pred & rblk[block[gid]]) if False else None
    ek = np.asarray(dec.e_ukey)
    kinds = collections.Counter()
    legal = collections.Counter()
    per = collections.Counter()
    dominated = collections.Counter()   # (all extras S, strict-subset of another FULL group of the block)
    gs, gz = np.asarray(dec.gstart), np.asarray(dec.gsize)
    # per block: groups list (only refused blocks)
    gb = np.flatnonzero(rblk[block])
    order = np.argsort(block[gb], kind="stable")
    gb = gb[order]
    bb = block[gb]
    lo = np.searchsorted(bb, np.arange(dec.nblocks + 1)[:0])  # unused
    ub, st = np.unique(bb, return_index=True)
    en = np.r_[st[1:], len(gb)]
    span = {int(b): gb[a:z] for b, a, z in zip(ub, st, en)}
    setu = np.zeros(len(dec.ukey_block), bool)
    setu[uk] = True
    sblk = dec.ukey_block[uk]
    so = np.argsort(sblk, kind="stable")
    sbs, sus = sblk[so], uk[so]
    for g in R.tolist():
        b = int(block[g])
        own = set(ek[gs[g]:gs[g] + gz[g]][pred[gs[g]:gs[g] + gz[g]]].tolist())
        a, z = np.searchsorted(sbs, b), np.searchsorted(sbs, b, "right")
        extras = [u for u in sus[a:z].tolist() if u not in own]
        # who predicts each extra
        pm = collections.defaultdict(set)
        dom = 0
        for h in span[b].tolist():
            if h == g:
                continue
            eh = ek[gs[h]:gs[h] + gz[h]][pred[gs[h]:gs[h] + gz[h]]]
            if full[h] and own < set(eh.tolist()):
                dom += 1
            for u in eh.tolist():
                pm[u].add(int(gdest[h]))
        cl = []
        for u in extras:
            if u not in pm:
                cl.append("N")
            elif int(gdest[g]) in pm[u]:
                cl.append("S")
            else:
                cl.append("O")
        sig = "".join(sorted(cl))
        dominated[sig == "S" * len(sig), dom > 0] += 1
        kinds[sig] += 1
        k = b * (N + 1) + int(gdest[g]) + 1
        nfull = int(kc[np.searchsorted(kk, k)])
        legal["sole" if nfull == 1 else "multi"] += 1
        per[(sig == "S" * len(sig) and len(sig) > 0, nfull == 1)] += 1
    res = dict(full=int(full.sum()), fired=int(fired.sum()), refused=len(R), kinds=dict(kinds.most_common(12)),
               legal=dict(legal), allS_sole=per[(True, True)], allS=per[(True, True)] + per[(True, False)],
               dominated={str(k): v for k, v in dominated.items()})
    log.info("RESULT %s", res)
    if out is not None:
        out.update(res)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_relax_analysis.log"))])
    import cycloneiv_ddb_blockmap as BM
    g = cg.load(cg.die_of("EP4CGX150"))
    plane = cc.cram_plane(open(a.image, "rb").read(), g)
    dec = ad.Dec()
    ge = BM.group_edges()
    gdest = np.where(ge["real"], ge["dest"], -1).astype(np.int64)
    analyse(plane, dec, gdest)


if __name__ == "__main__":
    main()
