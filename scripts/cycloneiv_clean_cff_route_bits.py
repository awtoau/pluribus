#!/usr/bin/env python3.15t
"""Routing bits stored in the CFF address space (#176, ledger T-007).

  python3.15t scripts/cycloneiv_clean_cff_route_bits.py [--no-corpus]
Log tmp/logs/cycloneiv_clean_cff_route_bits.log.

Rule from code: DYGR_ROUTE_ASM_BIT::operator<< (libddb_dygr@0x2caf80) reads four i8-delta flag fields per entry
(use-encoded, encoded-high, variant, address-space tag); get_flat_address@0x23ab50 ORs 0xA0000000 (CFF) when the tag is set.
Step 1 (asm.ddb only): list every entry whose tag running sum is 1 and the edges / records it belongs to.
Step 2 (confirmation only): for every corpus RCF edge whose group is CFF-tagged, read the CFF bit and compare with the required value.
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_cff_route_bits.log")
log = logging.getLogger("cff_route_bits")


def flag_runs(flag):
    """-> (use_encoded, encoded_high, variant, tag) running-sum bits per entry (i8 deltas, value = sum & 1)."""
    f = np.asarray(flag).astype(np.int64)
    out = []
    for i in range(4):
        b = (((f >> (8 * i)) & 0xFF) ^ 0x80) - 0x80
        out.append((np.cumsum(b) & 1).astype(np.uint8))
    return out


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG, "w")])
    from lifters.cycloneiv_clean import ddb, tracer as T
    rt, a = ddb.Routing(), ddb.Asm()
    f0, f1, var, tag = flag_runs(a.flag)
    want = np.where(f0 == 1, f1, 1).astype(np.uint8)
    pos = np.asarray(a.pos).astype(np.int64) & ddb.ADDR_MASK
    rec = np.asarray(a.rec)
    idx = np.flatnonzero(tag == 1)
    log.info("entries %d; variant set %d; tag set %d (all use-encoded: %s); records %d; CFF indices %d..%d, %d distinct",
             len(f0), int(var.sum()), len(idx), bool(f0[idx].all()), len(np.unique(rec[idx])), pos[idx].min(), pos[idx].max(), len(set(pos[idx].tolist())))
    tagged = {}                                   # (src record, group k) -> ([cff idx], [want])
    for r in np.unique(rec[idx]):
        nf = len(rt.fanout(int(r)))
        for k in range(len(a.group_sizes(int(r)))):
            sl = a.group_slice(int(r), k)
            t = tag[sl]
            if not t.any():
                continue
            if not t.all():
                log.info("MIXED group record %d k %d", r, k)
            tagged[(int(r), k)] = (pos[sl].tolist(), want[sl].tolist(), k < nf)
    kinds = collections.Counter()
    for (r, k), (ad, w, real) in tagged.items():
        kinds[(rt.element(r)[0], "edge" if real else "exclusion", len(ad))] += 1
    for key, c in sorted(kinds.items()):
        log.info("source enum %d %s group of %d bits: %d", key[0], key[1], key[2], c)
    if "--no-corpus" in sys.argv:
        return
    from lifters.cycloneiv_clean import cycloneiv_io as IO
    cff = IO.Cff()
    rs = T.Resolver(rt)
    root = os.path.join(REPO, "corpus", "cycloneiv")
    tot = collections.Counter()
    for d in sorted(os.listdir(root)):
        rcf, rbf = os.path.join(root, d, "routing.rcf"), os.path.join(root, d, "bitstream.rbf")
        if not (os.path.exists(rcf) and os.path.exists(rbf)):
            continue
        edges = set()
        for net in T.parse_rcf(rcf):
            edges.update(net["edges"])
        if not edges:
            continue
        pa = sorted(edges)
        ids, why = rs.resolve([p for p, c in pa] + [c for p, c in pa])
        n = len(pa)
        hit = []
        for i in range(n):
            s, dd = int(ids[i]), int(ids[n + i])
            if s < 0 or dd < 0:
                continue
            fo = rt.fanout(s)
            w = np.flatnonzero(fo == dd)
            if len(w) and (s, int(w[0])) in tagged:
                hit.append((pa[i], s, int(w[0])))
        if not hit:
            continue
        vals, _ = cff.read(rbf)
        for (pc, s, k) in hit:
            ad, w, _ = tagged[(s, k)]
            got = [int(vals[x]) for x in ad]
            ok = got == w
            tot["match" if ok else "mismatch"] += 1
            if not ok:
                log.info("%s %s -> %s: want %s got %s", d, pc[0][0], pc[1][0], w, got)
    log.info("corpus edges on CFF-tagged groups: %s", dict(tot))


if __name__ == "__main__":
    main()
