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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", required=True)
    ap.add_argument("--designs", default="gx150_sp_*")
    ap.add_argument("--split", default="odd")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_learner_baseline.log", "w")])
    dec = rd.Decoder(a.tables.split(","))
    names = [n for n in cc.designs(a.designs) if rl.split_of(n, a.split)][:a.limit]
    geom = rl.one_geom(names)
    tot, why = collections.Counter(), collections.Counter()
    nok = nall = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for name, c, w, ok, al in ex.map(lambda n: rs.score_design(n, dec, geom), names):
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
