#!/usr/bin/env python3.15t
"""Held-out-LAB confirmation of the control-shift hypothesis (#165, follows cycloneiv_blkrba_control.py).
H2c: named control bit (dx, dy) of the vendor LAB table sits at tile-relative (df, dv) = (dy - 22, 2 - dx)
(LUT bits: dy - 15; control bits: constant 22, i.e. the -7 shift fitted on 3 cells at X10Y10/X58Y30).
Vendor name strings are never written: groups by size (cnt16 = 16 counter-type, mux9 = 9 mux-type, rowclk18).

PREDICTION (written before any build).  Single-knob pairs, bit_hunter family B (ONE FF in the test LE, control sources
as idle LUTs, control nets from pins, same back-annotated routing in both builds, distinct net per LUT port, nulls first).
Predicted cells inside the pair diff (tile-relative (df, dv); role index = position in the size-sorted group):
  knob            predicted cells (df, dv)            named identity (H2c)
  clk vs ~clk     (-6,-30)                            cnt16 #1
  ena absent/pin  (-8,-30), (-7,-30)                  cnt16 #2, cnt16 #0
  aclr absent/pin (-1,-32), (0,-32)                   mux9  #4, mux9  #3
  sclr absent/pin (2,-32)                             mux9  #2
6 cells per LAB.  The cell POSITIONS are already measured at X10Y10 / X58Y30 (LAB-independent there); the new content
is (a) replication at LABs of other column classes, (b) the named identity, which is an assignment and cannot be
checked by position alone: no named cell of rowclk18 and none of the other cnt16 / mux9 indices may be in these
diffs more often than chance (counted and reported as extras).
HELD-OUT LABs (none used before): X22Y40 (M9K-adjacent, left of an M9K column), X30Y20 (pitch-39 column), X50Y45 (plain interior).
REFUTED if: fewer than 4 of 6 predicted cells in the diffs at a LAB, or a predicted cell absent from its matching knob
(or present in an unrelated knob's diff).  Claims registered only if confirmed at >= 3 LABs.
Builds: 3 LABs x (boot + base + 4 variants) = 18, + 2 null builds = 20 (cap 24), <= 6 concurrent.
Nulls first: renamed design and other seed must give an empty diff.

ROUND 2 (corners, prediction written before any corner build): same table, same 6 cells per LAB, tile-relative,
at X1Y1 and X116Y90 (extremes of the LAB array; edge LABs are their own class).  Same refutation rule (< 4 / 6 at a LAB,
or a predicted cell absent from its knob / present in an unrelated knob).  Null pair at X1Y1 first.  Builds: 2 x 6 + 2 = 14.
Five scopes then: X22Y40, X30Y20, X50Y45, X1Y1, X116Y90 (X10Y10 / X58Y30 were fit data).

  python3.15t scripts/cycloneiv_blkrba_hold.py build [--jobs 6] [--round 2]
  python3.15t scripts/cycloneiv_blkrba_hold.py analyse [--record]
Log tmp/logs/cycloneiv_blkrba_hold.log; result tmp/blkrba_hold.json
"""
import argparse
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_bit_hunter as bh  # noqa: E402
import cycloneiv_blkrba_control as bc  # noqa: E402
import cycloneiv_blkrba_lab as bl  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402

log = logging.getLogger("cycloneiv_blkrba_hold")
LABS = [(22, 40), (30, 20), (50, 45)]
CORNERS = [(1, 1), (116, 90)]
SHIFT = -7
KNOBS = {"clk": {"clk": "~KA"}, "ena": {"ena": "enap"}, "aclr": {"clr": "clrp"}, "sclr": {"sclr": "sclp"}}
PRED = {"clk": [(-6, -30)], "ena": [(-8, -30), (-7, -30)], "aclr": [(-1, -32), (0, -32)], "sclr": [(2, -32)]}
NULL_LAB = (30, 20)


def base(lab):
    return {**bh.base_b(lab), "ff": 1, "pins": 1}


def variants(lab):
    b = base(lab)
    return b, {k: {**b, **v} for k, v in KNOBS.items()}


def pair_rel(g, lab, na, nb):
    f0, v0 = g.anchor(*lab)
    return {(k // bh.NV - f0, k % bh.NV - v0) for k, _ in bh.pair_cells(bh.tagged(na), bh.tagged(nb))}


def setup_log():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    for lg in (log, bh.log, bh.fz.log):
        lg.setLevel(logging.INFO)
        for h in (logging.FileHandler(REPO / "tmp/logs/cycloneiv_blkrba_hold.log"), logging.StreamHandler()):
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            lg.addHandler(h)


def build(jobs, labs, null_lab):
    b = base(null_lab)
    nulls = [(b, {**b, "nm": "r"}), (b, {**b, "seed": 2})]
    bh.run_variants([p for pr in nulls for p in pr], min(jobs, 2))
    ok = bh.okvars()
    g = cg.load("ep4cgx150")
    for pa, pb in nulls:
        na, nb = bh.pname(pa), bh.pname(pb)
        if na not in ok or nb not in ok:
            sys.exit(f"null build missing {na} {nb}")
        n = len(bh.pair_cells(bh.tagged(na), bh.tagged(nb)))
        log.info("NULL %s: diff cells %d", bh.knob_of(pa, pb), n)
        if n:
            sys.exit("NULL CONTROL FAILED: stop")
    pl = []
    for lab in labs:
        b, vs = variants(lab)
        pl += [b] + list(vs.values())
    bh.run_variants(pl, jobs)


def analyse(record, labs):
    g = cg.load("ep4cgx150")
    ctl = bc.named_control(bl.DEFAULT_CSV)
    role_of = {}
    for r, v in ctl.items():
        for i, sub, df, dv in v:
            role_of[(df + SHIFT, dv)] = (r, i)
    ok = bh.okvars()
    out = {}
    tot_found = 0
    rec = []
    for lab in labs:
        b, vs = variants(lab)
        nb = bh.pname(b)
        row = {}
        if nb not in ok:
            log.info("LAB %s: base not built", lab)
            continue
        found_lab = 0
        diffs = {}
        for k, p in vs.items():
            n = bh.pname(p)
            if n not in ok:
                row[k] = "not built"
                continue
            d = pair_rel(g, lab, n, nb)
            diffs[k] = d
        for k, d in diffs.items():
            pred = set(PRED[k])
            hit = pred & d
            found_lab += len(hit)
            extras_named = sorted((c, role_of[c]) for c in d if c in role_of and c not in pred)
            unrelated = {o: sorted(pred & diffs[o]) for o in diffs if o != k and pred & diffs[o]}
            row[k] = {"diff_cells": len(d), "predicted": len(pred), "found": len(hit), "found_cells": sorted(hit),
                      "named_extras": extras_named, "pred_in_unrelated": unrelated,
                      "roles": [role_of[c] for c in sorted(hit)]}
            log.info("LAB %s knob %-5s diff %2d cells: predicted %d found %d %s | roles %s | other named in diff %s | predicted cells in other knobs %s",
                     lab, k, len(d), len(pred), len(hit), sorted(hit), row[k]["roles"], extras_named, unrelated)
            if record:
                rec.append((lab, k, d, nb, bh.pname(vs[k])))
        row["found_total"] = found_lab
        tot_found += found_lab >= 4
        log.info("LAB %s: %d / 6 predicted cells found -> %s", lab, found_lab, "ok" if found_lab >= 4 else "REFUTED")
        out[str(lab)] = row
    log.info("LABs with >= 4 / 6: %d / %d", tot_found, len(labs))
    (REPO / ("tmp/blkrba_hold.json" if labs == LABS else "tmp/blkrba_hold_corners.json")).write_text(json.dumps(out, indent=1, default=list))
    if record:
        from provenance import evidence_io as E
        from provenance import corpus as CO
        import db
        with db.engine().begin() as conn:
            E.ensure_family(conn, "cycloneiv")
            for lab, k, d, nb, nv in rec:
                A, R = [], []
                for key, in_a in bh.pair_cells(bh.tagged(nv), bh.tagged(nb)):
                    (A if in_a else R).append(key)
                meta = {"group": "blkrba_hold", "knob": k, "lab": list(lab), "tile": list(lab), "predicted": PRED[k], "plane_level": True}
                E.record_specimen(conn, "cycloneiv", bh.lm.EV_DEVICE, f"hold_{lab[0]}x{lab[1]}_{k}", nb, A, R, meta,
                                  f"blkrba_hold:{k}", "scripts/cycloneiv_blkrba_hold.py", E.git_head(REPO), bh.NV,
                                  tool_version="25.1", level=3, build_base=CO.build_id(conn, "cycloneiv", nb),
                                  build_spec=CO.build_id(conn, "cycloneiv", nv))
        log.info("recorded %d evidence rows", len(rec))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("build", "analyse"))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    setup_log()
    if a.jobs > 6:
        sys.exit("cap: <= 6 concurrent")
    labs = LABS if a.round == 1 else CORNERS
    build(a.jobs, labs, NULL_LAB if a.round == 1 else CORNERS[0]) if a.cmd == "build" else analyse(a.record, labs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
