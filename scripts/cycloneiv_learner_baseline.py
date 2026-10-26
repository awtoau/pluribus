#!/usr/bin/env python3.15t
"""Learner (cycloneiv_route_learn tables) pip score on an explicit design list, for a like-for-like
comparison with the asm decode (cycloneiv_asm_decode.py score --limit N uses the same first N designs).

  python3.15t scripts/cycloneiv_learner_baseline.py --tables tmp/cycloneiv/rl_gx_m8.json --split odd --limit 20
Log tmp/logs/cycloneiv_learner_baseline.log
"""
import argparse
import collections
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_route_decode as rd  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402
import cycloneiv_route_score as rs  # noqa: E402

log = logging.getLogger("cycloneiv_learner_baseline")


def score_design_alias(name, dec, geom):
    """cycloneiv_route_score.score_design, but a source decoded from the asm tables is a physical wire
    whose RCF aliases are all returned: matched iff the oracle's name is one of them."""
    d = cc.load(name)
    plane, vo = d["plane"], d["vo"]
    c, why = collections.Counter(), collections.Counter()
    net_ok = net_all = 0
    for net, edges in d["rcf"].items():
        ok_net, any_edge = True, False
        for src, dst in edges:
            a, b = rl.node_at(vo, src), rl.node_at(vo, dst)
            if a is None or b is None:
                continue
            any_edge = True
            bx, by, bkey = b
            sx, sy, skey_ = a
            want = rs.skey(skey_ + (sx - bx, sy - by))
            cands, reason = dec.sources(plane, geom, bkey, bx, by)
            if not cands:
                c["missing"] += 1
                why[(reason, bkey[0])] += 1
                ok_net = False
            elif want in cands and (len(cands) == 1 or reason == "asm alias"):
                c["matched"] += 1
                why[("matched", bkey[0])] += 1
            elif len(cands) > 1:
                c["missing"] += 1
                why[("ambiguous pattern", bkey[0])] += 1
                ok_net = False
            else:
                c["wrong"] += 1
                why[("wrong", bkey[0])] += 1
                ok_net = False
        if any_edge:
            net_all += 1
            net_ok += ok_net
    used = {(k, x, y) for k, x, y, _s in rl.instances(name, d, geom)}
    touched = {(x, y) for _k, x, y in used}
    import random
    import zlib
    rnd = random.Random(zlib.crc32(name.encode()))
    labs = [(x, y) for x in geom.kind if geom.kind[x] == "LAB" for y in range(1, geom.ymax)]
    other = rnd.sample([t for t in labs if t not in touched], min(rs.EXTRA_SAMPLE, len(labs)))
    for (x, y) in list(touched) + other:
        if x in geom.kind and 0 <= y <= geom.ymax:
            e = dec.extra_in_tile(plane, geom, x, y, used)
            c["extra"] += e
            why[("extra", "tile")] += e
    return name, c, why, net_ok, net_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", required=True)
    ap.add_argument("--asm", action="store_true", help="asm tables first (cycloneiv_route_decode.AsmSource), learner fallback")
    ap.add_argument("--designs", default="gx150_sp_*")
    ap.add_argument("--split", default="odd")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_learner_baseline.log", "w")])
    dec = rd.Decoder(a.tables.split(","), asm=rd.AsmSource() if a.asm else None)
    names = [n for n in cc.designs(a.designs) if rl.split_of(n, a.split)][:a.limit]
    geom = rl.one_geom(names)
    tot, why = collections.Counter(), collections.Counter()
    nok = nall = 0
    with ThreadPoolExecutor(1 if a.asm else a.workers) as ex:
        for name, c, w, ok, al in ex.map(lambda n: score_design_alias(n, dec, geom), names):
            tot.update(c)
            why.update(w)
            nok, nall = nok + ok, nall + al
    den = sum(tot.values())
    log.info("designs %d (%s): pips matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.2f%%", len(names), a.tables,
             tot["matched"], tot["matched"], tot["missing"], tot["extra"], tot["wrong"], 100 * tot["matched"] / max(den, 1))
    log.info("nets: %d / %d all pips matched (%.2f%%)", nok, nall, 100 * nok / max(nall, 1))
    for t in sorted({tt for _, tt in why}, key=lambda t: -sum(v for (r, tt), v in why.items() if tt == t)):
        m, w = why[("matched", t)], why[("wrong", t)]
        miss = sum(v for (r, tt), v in why.items() if tt == t and r not in ("matched", "wrong"))
        log.info("  %-22s matched %7d missing %7d wrong %5d  %6.2f%%", t, m, miss, w, 100 * m / max(m + miss + w, 1))


if __name__ == "__main__":
    main()
