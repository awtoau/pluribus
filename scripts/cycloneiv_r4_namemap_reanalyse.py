#!/usr/bin/env python3.15t
"""Cyclone IV: re-read existing forced LB -> R4 name-map rows with the measured per-column (dx, df) applied (#162). 0 builds.

QUESTION: with the measured (dx, df) for (destination column, source rel), does each forced R4 name I resolve to ONE
record (dir, template idx, dx), independent of tile row and of the other columns of the same pitch class?
PREDICTION: yes.  REFUTED by two arcs with equal (I, dest column, rel) resolving to different records (row independence),
or equal (I, pitch class, rel) differing across columns (column independence is reported, not part of the refutation
of row independence).
Resolution: candidate of the LB source's R4 fan-out with dx == table dx and table df among its rigid-shift fits (|df| <= 80
stored, first 3 fits).  No table cell / no matching candidate = unresolved (counted missing).
Log tmp/logs/cycloneiv_r4_namemap_reanalyse.log.
"""
import collections
import glob
import json
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_r4_coltable as CT  # noqa: E402

log = logging.getLogger("namemap_reanalyse")


def main():
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_r4_namemap_reanalyse.log", mode="w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    tab = CT.table()
    log.info("table cells: %d", len(tab))
    arcs, why = [], collections.Counter()
    for f in sorted(glob.glob(str(REPO / "tmp/hop_specimens/results_r4*.json"))):
        for r in json.loads(Path(f).read_text())["rows"]:
            if r.get("wire") != "R4" or not r.get("honoured") or not r.get("cands"):
                why["not honoured / no cands"] += 1
                continue
            X, Y = r["tile"]
            rel = r.get("rel", r["lb"][1] - X)
            cell = tab.get((X, rel))
            if cell is None:
                why["no table cell"] += 1
                continue
            dx, df = cell
            hit = [c for c in r["cands"] if c["dx"] == dx and df in c["fits"]]
            if len(hit) != 1:
                why[f"{len(hit)} candidates at table (dx, df)"] += 1
                continue
            c = hit[0]
            arcs.append({"I": r["I"], "X": X, "Y": Y, "rel": rel, "rec": (c["dir"], c["idx"], c["dx"], c["dy"]), "file": os.path.basename(f)})
    log.info("arcs: %d resolved with table; dropped: %s", len(arcs), dict(why))
    byk = collections.defaultdict(set)
    for a in arcs:
        byk[(a["I"], a["X"], a["rel"])].add(a["rec"])
    multi = {k: v for k, v in byk.items() if len(v) > 1}
    rep = collections.Counter(a["I"] for a in arcs)
    n_dup = sum(1 for k in byk if sum(1 for a in arcs if (a["I"], a["X"], a["rel"]) == k) > 1)
    log.info("keys (I, dest X, rel): %d; keys with >1 arc: %d; CONTRADICTIONS (same key, different record): %d", len(byk), n_dup, len(multi))
    for k, v in sorted(multi.items()):
        log.info("  contradiction %s -> %s", k, sorted(v))
    log.info("distinct I covered: %d of 0..32 %s", len({a['I'] for a in arcs}), sorted({a['I'] for a in arcs}))
    cols = collections.defaultdict(set)
    for a in arcs:
        cols[(a["I"], a["rel"])].add((a["X"], a["rec"]))
    for k in sorted(cols):
        recs = {r for _, r in cols[k]}
        log.info("I=%2d rel=%+d: columns %s records %s", k[0], k[1], sorted({x for x, _ in cols[k]}), sorted(recs))


if __name__ == "__main__":
    main()
