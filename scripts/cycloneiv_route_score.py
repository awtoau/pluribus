#!/usr/bin/env python3.15t
"""Score learnt Cyclone IV routing tables against the RCF of (held-out) designs.

Per RCF edge (dst instance, src): read the dst group's mux bits at its tile, find the source whose
pattern equals them.
- matched: decoded source == RCF source
- wrong:   decoded a different source
- missing: no table for the group, or the bits match no known pattern
- extra:   a dst the RCF does not use whose mux bits are non-zero and match a pattern
Per net: matched when every edge of the net is matched.

  python3.15t scripts/cycloneiv_route_score.py --tables tmp/cycloneiv/route_learn_even.json --split odd
Log tmp/logs/cycloneiv_route_score.log
"""
import argparse
import collections
import json
import logging
import random
import zlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_route_decode as rd  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_route_score")
EXTRA_SAMPLE = 60   # untouched LAB tiles per design checked for extra connections


def skey(src):
    return "|".join(map(str, src))


def score_connections(name, dec, geom):
    """Per RCF sink with a fabric location: trace from the sink through decoded muxes to a driving
    cell (bitstream only) and compare with the net's driver atom."""
    d = cc.load(name)
    plane, vo = d["plane"], d["vo"]
    c, why = collections.Counter(), collections.Counter()
    tr = rd.Tracer(dec, plane, geom)
    for net, edges in d["rcf"].items():
        drv = rl.node_at(vo, ("DRV", net))
        for _src, dst in edges:
            if dst[0] != "SINK":
                continue
            b = rl.node_at(vo, dst)
            if b is None or drv is None:
                continue
            bx, by, bkey = b
            want = ("DRV", drv[2][1], drv[2][2], drv[0], drv[1])
            got, reason = tr.trace(bkey, bx, by)
            kind = f"{bkey[0]}.{bkey[2]}"
            if got is None:
                c["missing"] += 1
                why[(reason, kind)] += 1
            elif got == want:
                c["matched"] += 1
                why[("matched", kind)] += 1
            else:
                c["wrong"] += 1
                why[("wrong", kind)] += 1
    return name, c, why, 0, 0


def score_design(name, dec, geom):
    d = cc.load(name)
    plane = d["plane"]
    c = collections.Counter()
    why = collections.Counter()
    net_ok = net_all = 0
    vo = d["vo"]
    for net, edges in d["rcf"].items():
        ok_net, any_edge = True, False
        for src, dst in edges:
            a, b = rl.node_at(vo, src), rl.node_at(vo, dst)
            if a is None or b is None:
                continue
            any_edge = True
            bx, by, bkey = b
            sx, sy, skey_ = a
            want = skey(skey_ + (sx - bx, sy - by))
            got, reason = dec.source(plane, geom, bkey, bx, by)
            if got is None:
                c["missing"] += 1
                why[(reason, bkey[0])] += 1
                ok_net = False
            elif got == want:
                c["matched"] += 1
                why[("matched", bkey[0])] += 1
            else:
                c["wrong"] += 1
                why[("wrong", bkey[0])] += 1
                ok_net = False
        if any_edge:
            net_all += 1
            net_ok += ok_net
    # extra: unused muxes in touched tiles + EXTRA_SAMPLE seeded untouched LAB tiles
    used = {(k, x, y) for k, x, y, _s in rl.instances(name, d, geom)}
    touched = {(x, y) for _k, x, y in used}
    rnd = random.Random(zlib.crc32(name.encode()))
    labs = [(x, y) for x in geom.kind if geom.kind[x] == "LAB" for y in range(1, geom.ymax)]
    other = rnd.sample([t for t in labs if t not in touched], min(EXTRA_SAMPLE, len(labs)))
    for (x, y) in list(touched) + other:
        if x in geom.kind and 0 <= y <= geom.ymax:
            e = dec.extra_in_tile(plane, geom, x, y, used)
            c["extra"] += e
            why[("extra", "tile")] += e
    return name, c, why, net_ok, net_all


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", required=True)
    ap.add_argument("--designs", default="rnd_*")
    ap.add_argument("--split", default="all", choices=["all", "even", "odd"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--connections", action="store_true", help="score sink -> driver traces, not single pips")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_route_score.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    dec = rd.Decoder(a.tables.split(","))
    names = [n for n in cc.designs(a.designs) if rl.split_of(n, a.split)]
    geom = rl.one_geom(names)
    tot, why = collections.Counter(), collections.Counter()
    nok = nall = 0
    with ThreadPoolExecutor(a.workers) as ex:
        fn = score_connections if a.connections else score_design
        for name, c, w, ok, al in ex.map(lambda n: fn(n, dec, geom), names):
            tot.update(c)
            why.update(w)
            nok, nall = nok + ok, nall + al
    den = sum(tot.values())
    log.info("designs %d (%s, split %s), tables %s", len(names), a.designs, a.split, a.tables)
    log.info("pips: matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.2f%%", tot["matched"],
             tot["matched"], tot["missing"], tot["extra"], tot["wrong"], 100 * tot["matched"] / max(den, 1))
    log.info("nets: %d / %d all pips matched (%.2f%%)", nok, nall, 100 * nok / max(nall, 1))
    types = sorted({t for _, t in why})
    log.info("  %-24s %9s %9s %9s %8s   missing by reason", "dst type", "matched", "missing", "wrong", "%")
    for t in sorted(types, key=lambda t: -sum(v for (r, tt), v in why.items() if tt == t)):
        m = why[("matched", t)]
        w = why[("wrong", t)]
        miss = {r: v for (r, tt), v in why.items() if tt == t and r not in ("matched", "wrong")}
        tot_t = m + w + sum(miss.values())
        log.info("  %-24s %9d %9d %9d %7.2f%%   %s", t, m, sum(miss.values()), w, 100 * m / max(tot_t, 1), miss)
    return 0


if __name__ == "__main__":
    sys.exit(main())
