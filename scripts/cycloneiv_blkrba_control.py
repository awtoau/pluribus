#!/usr/bin/env python3.15t
"""TEST 2 (control-type bits) of the vendor LAB bit-table hypothesis (#165): map the 43 named CONTROL bits
(3 groups: 16 counter-type, 9 mux-type, 18 row-clock-type) through H2 and compare with measured cells.
H2 (validated on the 256 LUT bits, cycloneiv_blkrba_lab.py): tile-relative (df, dv) = (dy - 15, 2 - dx),
i.e. frame = FX[X] + dy - 15, v = vy0 + 70*Y + 2 - dx.  Vendor name strings are never written: groups are
told apart by size (16 / 9 / 18) and index.  Input table: gitignored s1/blkrba_stingray_abs.csv.  DB read-only.

PREDICTION (written before the run)
- P1: the named control bits at their H2 cells are contained in the measured control diffs of the matching
  feature (clock-type diffs: clk, clkpin; port-type: ena, aclr, sclr, sload, asdata) and NOT in unrelated pairs.
  Row-clock-type cells appear only in the clk / clkpin sets; mux-type / counter-type cells in the others or none.
- P2: the measured port cells (ena 2, aclr 3, sclr 2, clock polarity 1) coincide with named cells.
REFUTED if: containment < 50 % for a feature (named-bit group matched to it), or the same named position shows
in unrelated pairs as often as in the matching ones.  Chance level: the 43-position set translated over the
LAB window (all offsets), H2's containment ranked against that.
Pairs: cycloneiv_ctrl evidence rows (17 pairs x 4 LABs a..d = X10Y10, X58Y30, X37Y60, X100Y75), diff cells made
tile-relative to the LAB under test.  Sampling plan for the geometric checks: 4 corner LABs + seeded interior LABs.

  python3.15t scripts/cycloneiv_blkrba_control.py [--csv ...] [--seed 1] [--interior 20]
Log tmp/logs/cycloneiv_blkrba_control.log; result tmp/blkrba_control.json
"""
import argparse
import collections
import json
import logging
import os
import random
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "databases/cycloneiv/gx150.db"))
import cycloneiv_blkrba_lab as bl  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_le_locate as ll  # noqa: E402
from provenance import evidence_io as E  # noqa: E402

log = logging.getLogger("cycloneiv_blkrba_control")
DB = REPO / "databases/cycloneiv/gx150.db"
EVER = REPO / "databases/cycloneiv/ever_set.npy"
NV = 6368
LABS = {"a": (10, 10), "b": (58, 30), "c": (37, 60), "d": (100, 75)}
SETS = ["clk", "clkpin", "ena", "aclr", "sclr", "sload", "asdata"]
# measured single features (tile-relative (df, dv)); sources: docs/cycloneiv-bit-hunter.md (round 3/4)
MEASURED = {"clkpol(1c)": [(-6, -30)], "ena": [(-8, -30), (-7, -30)],
            "aclr": [(-1, -32), (0, -32), (3, -68)], "sclr": [(2, -32), (4, -1)]}
WIN_DF, WIN_DV = range(-19, 14), range(-68, 3)     # LAB window (FX-19..FX+13, v phase -68..2)


def named_control(path):
    """{role: [(idx, sub, df, dv)]}: groups of non-LUT names by size 16 / 9 / 18 (no name strings kept)."""
    names = bl.load_csv(path)
    groups = collections.defaultdict(list)
    for n, (dx, dy) in names.items():
        if bl.LUT.match(n):
            continue
        m = re.search(r"([A-Za-z]+)(\d+)$", n)
        if not m:
            continue
        parts = n.split(":")
        sub = parts[-2][-1] if len(parts) >= 3 else "-"
        groups[m.group(1)].append((int(m.group(2)), sub, dy - 15, 2 - dx))
    role = {16: "cnt16", 9: "mux9", 18: "rowclk18"}
    out = {}
    for g, v in groups.items():
        if len(v) in role:
            out[role[len(v)]] = sorted(v)
    assert sorted(len(v) for v in out.values()) == [9, 16, 18], {k: len(v) for k, v in out.items()}
    return out


def diff_cells(sets):
    """{(lab, set, pair): set of tile-relative (df, dv)} from the ctrl evidence rows (read-only)."""
    g = cg.load("ep4cgx150")
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = {}
    for lab, (x, y) in LABS.items():
        f0, v0 = g.anchor(x, y)
        for s in sets:
            for nm, sb, bb in c.execute("SELECT name,bits_spec,bits_base FROM evidence WHERE kind='specimen-pair' "
                                        "AND source_ref=?", (f"cycloneiv_ctrl:{s}:{lab}",)):
                cells = set()
                for b in list(E.unpack(sb)) + list(E.unpack(bb)):
                    cells.add((int(b) // NV - f0, int(b) % NV - v0))
                out[(lab, s, nm.split("_", 3)[3])] = cells
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(bl.DEFAULT_CSV))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--interior", type=int, default=20)
    a = ap.parse_args()
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp/logs/cycloneiv_blkrba_control.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    ctl = named_control(a.csv)
    allpos = {r: {(df, dv) for _, _, df, dv in v} for r, v in ctl.items()}
    every = set().union(*allpos.values())
    log.info("named control bits: %s; distinct H2 tile-relative cells %d; df %d..%d dv %d..%d",
             {r: len(v) for r, v in ctl.items()}, len(every), min(p[0] for p in every), max(p[0] for p in every),
             min(p[1] for p in every), max(p[1] for p in every))
    res = {"counts": {r: len(v) for r, v in ctl.items()}}

    D = diff_cells(SETS)
    log.info("ctrl pairs loaded: %d (lab,set,pair) rows; per set %s", len(D),
             {s: sum(1 for k in D if k[1] == s) for s in SETS})

    # ---- per-feature containment ------------------------------------------------------------
    def union(lab, s):
        return set().union(*[v for k, v in D.items() if k[0] == lab and k[1] == s])

    def inter_pairs(lab, s):          # cells in EVERY pair of the set at this lab
        vs = [v for k, v in D.items() if k[0] == lab and k[1] == s]
        return set.intersection(*vs) if vs else set()

    feat = {}
    for s in SETS:
        U = {lab: union(lab, s) for lab in LABS}
        Uall = set.intersection(*U.values())                  # in the diffs at all 4 LABs
        row = {"union_cells_per_lab": {l: len(u) for l, u in U.items()}, "cells_all4": len(Uall), "roles": {}}
        for r, pos in allpos.items():
            per_lab = {l: len(pos & U[l]) for l in LABS}
            row["roles"][r] = {"n": len(pos), "per_lab": per_lab, "all4": len(pos & Uall),
                               "pos_all4": sorted(pos & Uall)}
        win = {(df, dv) for df in WIN_DF for dv in WIN_DV}
        inwin = Uall & win
        row["window_cells_all4"] = len(inwin)
        row["window_named_all4"] = len(inwin & every)
        row["unexplained_window_all4"] = len(inwin - every)
        # chance: translate the 43-set over every window offset, containment in Uall
        rates = []
        for ddf in range(-19, 14):
            for ddv in range(-66, 4):
                rates.append(len({(p[0] + ddf, p[1] + ddv) for p in every} & Uall))
        h2 = len(every & Uall)
        row["chance"] = {"h2": h2, "mean": round(float(np.mean(rates)), 2), "max": int(max(rates)),
                         "rank_ge": int(sum(1 for r in rates if r >= h2)), "offsets": len(rates)}
        feat[s] = row
        log.info("SET %-7s window cells (all-4-LAB) %d: named %d, unexplained %d | H2 hits %d of %d (chance mean %.2f, max %d, "
                 "offsets >= H2 %d / %d)", s, len(inwin), len(inwin & every), len(inwin - every), h2, len(every),
                 row["chance"]["mean"], row["chance"]["max"], row["chance"]["rank_ge"], len(rates))
        for r, v in row["roles"].items():
            log.info("   %-8s per-LAB %s all-4 %d / %d  %s", r, v["per_lab"], v["all4"], v["n"], v["pos_all4"])
    res["features"] = feat

    # ---- per-pair presence of each named position (unrelated-pair check) ---------------------
    pres = collections.defaultdict(lambda: collections.defaultdict(int))     # position -> set -> labs-with-hit (any pair)
    for pos in every:
        for s in SETS:
            pres[pos][s] = sum(1 for l in LABS if pos in union(l, s))
    shared = sum(1 for pos in every if sum(1 for s in SETS if pres[pos][s] == 4) > 1)
    anyset = sum(1 for pos in every if any(pres[pos][s] == 4 for s in SETS))
    log.info("named positions in some set's diff at all 4 LABs: %d / %d; of those in more than one set: %d", anyset,
             len(every), shared)
    res["position_presence"] = {"in_any_set_all4": anyset, "in_multiple_sets": shared}

    # ---- measured single cells vs named ------------------------------------------------------
    meas = {}
    for f, cells in MEASURED.items():
        rows = []
        for c in cells:
            hit = [r for r, p in allpos.items() if c in p]
            near = min(((abs(c[0] - p[0]) + abs(c[1] - p[1]), r, p) for r, ps in allpos.items() for p in ps))
            insets = {s: sum(1 for l in LABS if c in union(l, s)) for s in SETS}
            rows.append({"cell": c, "named_roles": hit, "nearest": near[:2] + (list(near[2]),), "in_set_labs": insets})
            log.info("MEASURED %-11s cell %s named %s nearest (L1 %d, %s, %s); LABs containing in set diffs %s", f, c, hit,
                     near[0], near[1], near[2], {s: v for s, v in insets.items() if v})
        meas[f] = rows
    res["measured"] = meas

    # ---- exploratory: translate the named set by (ddf, 0) (control constant != LUT constant), holdout fit ----
    stripe = [c for f, cs in MEASURED.items() for c in cs if -35 <= c[1] <= -30]
    def hits(ddf, cells):
        return len({(p[0] + ddf, p[1]) for p in every} & set(cells))
    fit_cells = MEASURED["clkpol(1c)"] + MEASURED["ena"]
    test_cells = MEASURED["aclr"][:2] + MEASURED["sclr"][:1]
    best = max(range(-40, 41), key=lambda d: (hits(d, fit_cells), -abs(d)))
    nzero = sum(1 for d in range(-40, 41) if hits(d, fit_cells) == len(fit_cells))
    log.info("EXPLORATORY shift (ddf,0): fit on 1c+ena (%d cells) best ddf %d (%d offsets fit all); holdout aclr+sclr in-stripe %d cells: hits %d / %d;"
             " all in-stripe measured %d: hits %d", len(fit_cells), best, nzero, len(test_cells), hits(best, test_cells), len(test_cells),
             len(stripe), hits(best, stripe))
    sh = {(p[0] + best, p[1]) for p in every}
    expl = {}
    for s_ in SETS:
        for lab in LABS:
            pass
        U = set.intersection(*[union(l, s_) for l in LABS])
        expl[s_] = len(sh & U)
        log.info("EXPLORATORY shifted set in %s diffs (all 4 LABs): %d / 43", s_, len(sh & U))
    res["exploratory_shift"] = {"ddf": best, "offsets_fit_all": nzero, "holdout_hits": hits(best, test_cells),
                                "holdout_n": len(test_cells), "containment": expl}

    # ---- collisions / geometry over the sampling plan ---------------------------------------
    g = cg.load("ep4cgx150")
    labs = json.loads((REPO / "lifters/data/cycloneiv_ep4cgx150_labs.json").read_text())["labs"]
    tiles = sorted({(int(x), int(y)) for x, y in labs if g.is_lab(int(x), int(y))})
    xs, ys = [t[0] for t in tiles], [t[1] for t in tiles]
    corners = [min(tiles, key=lambda t, cx=cx, cy=cy: abs(t[0] - cx) + abs(t[1] - cy))
               for cx in (min(xs), max(xs)) for cy in (min(ys), max(ys))]
    rnd = random.Random(a.seed)
    interior = rnd.sample([t for t in tiles if t not in corners], a.interior)
    plan = corners + interior
    # own-LAB cell classes (tile-relative): LUT bits (law), LE-used bit (1b), clock polarity (1c)
    lut = {(df, g.DN[le] + (-1 if le % 2 else 1) * dv) for le in range(16) for df, dv in ll.DK}
    leu = {(-8, g.DN[le] - (-1 if le % 2 else 1)) for le in range(16)}
    cls = {"lut": lut, "1b": leu, "1c": {(-6, -30)}}
    res["collisions"] = {c: len(every & s) for c, s in cls.items()}
    log.info("H2 control cells coinciding with LUT cells %d, LE-used cells %d, clock-polarity cell %d (tile-relative, same for every LAB)",
             *[len(every & cls[k]) for k in ("lut", "1b", "1c")])
    ever = None
    if EVER.exists():
        ever = np.unpackbits(np.load(EVER))
    rec = {}
    if ever is not None:
        for name, group in (("plan", plan), ("all", tiles)):
            tot = collections.Counter()
            hit = collections.Counter()
            for (x, y) in group:
                f0, v0 = g.anchor(x, y)
                for r, ps in allpos.items():
                    for df, dv in ps:
                        tot[r] += 1
                        hit[r] += int(ever[(f0 + df) * NV + v0 + dv])
            rec[name] = {r: [hit[r], tot[r]] for r in tot}
            log.info("ever-set (3,448 held bitstreams) at control cells, %s LABs (%d): %s", name, len(group),
                     {r: f"{hit[r]}/{tot[r]}={100*hit[r]/tot[r]:.1f}%" for r in tot})
        # reference: ever-set rate of the 1b and 1c cells and of unconstrained window cells
        for nm, ps in (("1b", leu), ("1c", cls["1c"])):
            h = t = 0
            for (x, y) in plan:
                f0, v0 = g.anchor(x, y)
                for df, dv in ps:
                    t += 1
                    h += int(ever[(f0 + df) * NV + v0 + dv])
            log.info("ever-set reference %s over plan LABs: %d/%d", nm, h, t)
    res["ever_set"] = rec
    res["plan"] = {"corners": corners, "interior_n": len(interior), "seed": a.seed}
    log.info("sampling plan: corners %s + %d seeded interior (seed %d)", corners, len(interior), a.seed)
    (REPO / "tmp/blkrba_control.json").write_text(json.dumps(res, indent=1, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
