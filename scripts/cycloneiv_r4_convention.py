#!/usr/bin/env python3.15t
"""Which coordinate convention resolves an R4 hop destination? (#160, owner; #157)

QUESTION: the gate (cycloneiv_ddb_trace.hop_forward) resolves an R4 destination as the unique
fan-out record in a +-3 x, +-1 y window of the RCF coordinate; the hop specimens use the exact tile.
Which is right?

PREDICTION (written before the first run; refuted if it fails):
  The exact-tile convention is right for the 23 forced R4 arcs (hop_specimen evidence rows,
  LAB-relative), and the gate's +-3 window resolves some R4 hops to a WRONG record: detected as a
  window pick that differs from the record the post-fit RCF names for the same hop.
Ground truth = RCF-named record: fan-out records of the source whose vendor wire name is in the
learnt alias set of the RCF destination form (Tables.src_matches); vendor output, not our decoder.
Convention (a) exact tile, (b) +-3/+-1 window unique, (c) nearest (L1, ties ambiguous).

  python3.15t scripts/cycloneiv_r4_convention.py [--designs 'gx150_rb*'] [--split odd] [--limit N]
Log tmp/logs/cycloneiv_r4_convention.log.
"""
import argparse
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_asm_tables as AT  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_ddb_trace as DT  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_r4_convention")
CLASSES = ("R4", "C4", "R24", "C16")


def col_class(g, X):
    """39 if the 2-column span (X-1, X) holds a 39-frame column, else 35."""
    fx = g.FX
    return 39 if any(x in fx and x - 1 in fx and fx[x] - fx[x - 1] == 39 for x in (X, X - 1)) else 35


def convs(D, fan, enum, tx, ty, dvx, dvy):
    Q, P = D.Q, D.P
    m = fan[Q.enum[fan] == enum]
    dx, dy = P.vx[m] - tx, P.vy[m] - ty
    ex = m[(dx == 0) & (dy == 0)]
    wi = m[(np.abs(dx) <= dvx) & (np.abs(dy) <= dvy)]
    d1 = np.abs(dx) + np.abs(dy)
    if len(m):
        nn = m[d1 == d1.min()]
    else:
        nn = m
    return {"exact": ex, "window": wi, "nearest": nn}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--designs", default="gx150_rb*")
    ap.add_argument("--split", default="odd")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_r4_convention.log"))])
    names = [n for n in cc.designs(a.designs) if rl.split_of(n, a.split)]
    if a.limit:
        names = names[:a.limit]
    D = DT.Ddb(need_map=False)
    T, Q, P = D.T, D.Q, D.P
    geom = P.g
    # tally[cls][pitch][conv][outcome]; outcome: agree / wrong (picked other) / none / ambig
    tally = collections.defaultdict(collections.Counter)
    truth_n = collections.defaultdict(collections.Counter)
    offs = collections.defaultdict(collections.Counter)
    for di, name in enumerate(names):
        d = cc.load(name)
        pips, _ = AT.oracle(name, d, geom)
        children = collections.defaultdict(list)
        for dn, sn in pips.items():
            children[sn].append(dn)
        stack = []
        for sn in list(children):
            base = T.unnamed.get((sn[0], str(sn[2]))) if sn[0] == "LE_BUFFER" else None
            if base is not None and sn[3] in T.colrank:
                stack.append((sn, base + 90 * T.colrank[sn[3]] + sn[4]))
        while stack:
            sn, rs = stack.pop()
            if not 0 <= rs < D.N:
                continue
            fan = D.fan_of(rs)
            for dn in children.get(sn, ()):
                typ = dn[0]
                if typ not in DT.WIRE_T:
                    continue
                enum = DT.ENUM_OF[typ]
                cand = fan[Q.enum[fan] == enum]
                tr = [int(r) for r in cand if T.src_matches(int(r), dn)]
                key = (typ, col_class(geom, dn[3]))
                if len(tr) != 1:
                    truth_n[key]["truth none" if not tr else "truth ambiguous"] += 1
                    continue
                truth_n[key]["truth unique"] += 1
                rd = tr[0]
                tx, ty = DT.XM - dn[3], dn[4]
                offs[key][(int(P.vx[rd]) - tx, int(P.vy[rd]) - ty)] += 1
                dvx, dvy = DT.WIN_OF[typ]
                for cv, got in convs(D, fan, enum, tx, ty, dvx, dvy).items():
                    if len(got) == 0:
                        o = "none"
                    elif len(got) > 1:
                        o = "ambig" + ("+has_truth" if rd in got else "")
                    else:
                        o = "agree" if int(got[0]) == rd else "wrong"
                    tally[key + (cv,)][o] += 1
                stack.append((dn, rd))
        if di % 10 == 9:
            log.info("%d / %d designs", di + 1, len(names))
    log.info("== ground-truth availability (RCF-named record via alias) ==")
    for k in sorted(truth_n):
        log.info("  %s pitch %d: %s", k[0], k[1], dict(truth_n[k]))
    log.info("== convention vs RCF-named record ==")
    for k in sorted(tally):
        c = tally[k]
        tot = sum(c.values())
        log.info("  %-4s pitch %d %-8s n=%6d agree %6.2f%%  %s", k[0], k[1], k[2], tot, 100 * c["agree"] / max(1, tot), dict(c))
    log.info("== (record - RCF coordinate) offsets of the RCF-named record, top 6 ==")
    for k in sorted(offs):
        log.info("  %s pitch %d: %s", k[0], k[1], offs[k].most_common(6))


if __name__ == "__main__":
    main()
