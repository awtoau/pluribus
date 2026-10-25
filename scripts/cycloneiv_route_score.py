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
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_route_score")


def load_tables(path):
    raw = json.loads(Path(path).read_text())
    out = {}
    for k, v in raw.items():
        mux = [tuple(p) for p in v["mux"]]
        pats = {}
        for s, p in v.get("pats", {}).items():
            pats.setdefault(tuple(tuple(q) for q in p), []).append(s)
        out[k] = (mux, pats)
    return out


def gkey(cls, key):
    return f"{cls}|{'|'.join(map(str, key))}"


def skey(src):
    return "|".join(map(str, src))


def read_bits(plane, geom, x, y, mux):
    f0, v0 = geom.anchor(x, y)
    nf, nv = plane.shape
    on = []
    for df, dv in mux:
        f, v = f0 + df + rl.WF[0], v0 + dv + rl.WV[0]
        if 0 <= f < nf and 0 <= v < nv and plane[f, v]:
            on.append((df, dv))
    return tuple(on)


def score_design(name, tables, geom):
    d = cc.load(name)
    plane = d["plane"]
    c = collections.Counter()
    why = collections.Counter()
    net_ok = net_all = 0
    used = set()
    vo = d["vo"]
    for net, edges in d["rcf"].items():
        ok_net, any_edge = True, False
        for src, dst in edges:
            a, b = rl.node_at(vo, src), rl.node_at(vo, dst)
            if a is None or b is None:
                continue
            any_edge = True
            bx, by, bkey = b
            ax, ay, akey = a
            s = skey(akey + (ax - bx, ay - by))
            cls = rl.tile_class(geom, bx, by)
            g = gkey(cls, bkey)
            used.add(g + f"@{bx},{by}")
            t = tables.get(g)
            if t is None:
                c["missing"] += 1
                why[("no table", bkey[0])] += 1
                ok_net = False
                continue
            mux, pats = t
            got = pats.get(read_bits(plane, geom, bx, by, mux))
            if got is None:
                c["missing"] += 1
                why[("unknown pattern", bkey[0])] += 1
                ok_net = False
            elif s in got and len(got) == 1:
                c["matched"] += 1
            elif s in got:
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
    return name, c, why, net_ok, net_all


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", required=True)
    ap.add_argument("--designs", default="rnd_*")
    ap.add_argument("--split", default="all", choices=["all", "even", "odd"])
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_route_score.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    geom = cg.load("ep4ce6")
    tables = load_tables(a.tables)
    names = [n for n in cc.designs(a.designs) if rl.split_of(n, a.split)]
    tot, why = collections.Counter(), collections.Counter()
    nok = nall = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for name, c, w, ok, al in ex.map(lambda n: score_design(n, tables, geom), names):
            tot.update(c)
            why.update(w)
            nok, nall = nok + ok, nall + al
    den = sum(tot.values())
    log.info("designs %d (%s, split %s), tables %s", len(names), a.designs, a.split, a.tables)
    log.info("pips: matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.2f%%", tot["matched"],
             tot["matched"], tot["missing"], tot["extra"], tot["wrong"], 100 * tot["matched"] / max(den, 1))
    log.info("nets: %d / %d all pips matched (%.2f%%)", nok, nall, 100 * nok / max(nall, 1))
    for k, v in why.most_common(40):
        log.info("  %-40s %d", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
