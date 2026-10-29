#!/usr/bin/env python3.15t
"""Cyclone IV: does the forced R4 name -> record depend on destination row parity only? (#162)

QUESTION: at fixed destination column X47 and fixed (I, rel), is the resolved LB -> R4 record (dir, idx, dx) a function of
the destination ROW parity (even/odd) only -- not the exact row, not the source LAB row?
PREDICTION: yes.  REFUTED by (a) two same-parity destination rows (same I, rel, X) resolving to different records, or
(b) the source LAB row changing the record at one fixed destination.
Set 1: (I, rel) in a chosen list x >= 6 destination rows of X47 (both parities), source LAB on the destination row.
Set 2: one (I, rel), destination row fixed, source LAB row varied.
Resolution: record = fan-out candidate whose group cells, shifted by the table df of (X47, rel), lie in the raw diff;
ALL fitting shifts (|df| <= 140) are stored per candidate in the evidence row (no truncation).

  cycloneiv_r4_rowparity.py avail            # chains available at X47
  cycloneiv_r4_rowparity.py plan --out P
  cycloneiv_r4_relcol.py build --plan P [--nulls]     (builds)
  cycloneiv_r4_rowparity.py analyse --plan P
Log tmp/logs/cycloneiv_r4_rowparity.log.
"""
import argparse
import collections
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_hop_specimens as H  # noqa: E402
import cycloneiv_r4_name_map as N  # noqa: E402
import cycloneiv_r4_relcol as R  # noqa: E402

log = logging.getLogger("cycloneiv_r4_rowparity")
X = 47


def avail():
    """{(I, rel, Y): [(lb, li)]} for destination column X from corpus-seen chains."""
    out = collections.defaultdict(list)
    for (t, x, y, i), (lbs, lis) in R.chains().items():
        if x != X:
            continue
        for lb in lbs:
            for li in lis:
                if li[3] in H.LI_PORT:
                    out[(i, lb[1] - X, y)].append((lb, li))
    return out


def cmd_avail(a):
    av = avail()
    for (i, rel) in ((0, 0), (6, -1), (26, 3), (26, 4)):
        rows = sorted(y for (ii, r, y) in av if (ii, r) == (i, rel))
        same = sorted(y for y in rows if any(lb[2] == y for lb, _ in av[(i, rel, y)]))
        log.info("I=%d rel=%+d: rows %s; with source on same row: %s", i, rel, rows, same)


def mk(i, rel, y, lb, li):
    u0 = (lb[1], lb[2], H.n_of_i(lb[3]))
    same = (u0[0], u0[1]) == (li[1], li[2])
    u1 = (li[1], li[2], 6 if not (same and u0[2] == 6) else 8)
    return {"wire": "R4", "I": i, "tile": [X, y], "lb": list(lb), "wire_name": ["R4", X, y, i], "li": list(li),
            "u0": list(u0), "u1": list(u1), "port": H.LI_PORT[li[3]], "rel": rel}


def pick_rows(av, i, rel, n):
    ys = sorted(y for (ii, r, y) in av if (ii, r) == (i, rel) and any(lb[2] == y for lb, _ in av[(i, rel, y)]))
    pick = []
    for par in (0, 1):                      # both parities, spread over the range
        pk = [y for y in ys if y % 2 == par]
        pick += pk[:: max(1, len(pk) // ((n + 1) // 2))][: (n + 1) // 2]
    return sorted(pick)[:max(n, 2)] if n >= 4 else sorted(pick)


def best(av, i, rel, y, same=True):
    ps = [p for p in av[(i, rel, y)] if (p[0][2] == y) == same]
    return sorted(ps, key=lambda p: (abs(p[1][1] - X) + abs(p[1][2] - y), p))[0] if ps else None


def cmd_plan(a):
    av = avail()
    arcs = []
    for i, rel, n in ((0, 0, 6), (6, -1, 6)):
        for y in pick_rows(av, i, rel, n):
            lb, li = best(av, i, rel, y)
            arcs.append(dict(mk(i, rel, y, lb, li), set=1))
    # set 2: (I=1, rel 0): destination rows 24 and 40, source on the destination row and on the neighbouring row (corpus has only y, y+1)
    both = [y for (ii, r, y) in sorted(av) if (ii, r) == (1, 0) and best(av, 1, 0, y, True) and best(av, 1, 0, y, False)]
    log.info("I=1 rel 0 rows with both source rows: %s", both)
    for y in both[:2]:
        for same in (True, False):
            lb, li = best(av, 1, 0, y, same)
            arcs.append(dict(mk(1, 0, y, lb, li), set=2))
    Path(a.out).write_text(json.dumps({"tile": None, "arcs": arcs}))
    bases = {N.base_name(x) for x in arcs}
    log.info("plan: %d arcs, %d bases => %d builds", len(arcs), len(bases), len(arcs) + len(bases))
    for x in arcs:
        log.info("  set%d I=%d rel=%+d Y=%d from %s", x["set"], x["I"], x["rel"], x["tile"][1], x["lb"])


def cmd_analyse(a):
    import cycloneiv_r4_coltable as CT
    from provenance import evidence_io as E
    import db
    plan = json.loads(Path(a.plan).read_text())
    G = H.Graph()
    G.vx = lambda X_: G.D.vx_of(X_)
    tab = CT.table()
    rows = []
    for x in plan["arcs"]:
        nme, bnm = R.spec_name(x), N.base_name(x)
        row = dict(x)
        if not (H.CORPUS / nme / "bitstream.rbf").exists():
            rows.append(dict(row, status="not-built"))
            continue
        N.PFX = "gxr4df"
        ok, why = N.honoured(x)
        B, S_ = H.bits(bnm), H.bits(nme)
        on, off = sorted(S_ - B), sorted(B - S_)
        row.update(honoured=ok, why=why, on=on, off=off)
        if not ok:
            row["status"] = "not-honoured"
            rows.append(row)
            continue
        lb = tuple(x["lb"])
        s = G.lb.get((G.vx(lb[1]), lb[2], lb[3]))
        tvx, tvy = G.vx(X), x["tile"][1]
        onset = set(on)
        cands = []
        for k, d, g in N.candidates(G, s, "R4"):
            fits = N.shifts_fit(g, onset, 140)                     # ALL fitting shifts
            cands.append({"k": k, "rec": int(d), "dir": int(N.z_dir(G, d)), "dx": int(G.P.vx[d]) - tvx, "dy": int(G.P.vy[d]) - tvy,
                          "idx": int(G.Q.index[d]), "n": len(g), "fits": fits})
        cell = tab.get((X, x["rel"]))
        row["cands"] = cands
        row["table"] = cell
        hit = [c for c in cands if cell and c["dx"] == cell[0] and cell[1] in c["fits"]]
        anyfit = [c for c in cands if c["fits"]]
        row["status"] = "resolved" if len(hit) == 1 else f"unresolved({len(hit)} at table, {len(anyfit)} any fit)"
        row["resolved"] = hit[0] if len(hit) == 1 else None
        rows.append(row)
    Path(a.plan).with_name("results_rowpar.json").write_text(json.dumps({"rows": rows}, default=int))
    log.info("%-4s %-3s %-4s %-3s %-18s %s", "set", "I", "rel", "Y", "source", "status -> (dir, idx, dx, dy) table / all-fit candidates")
    for r in rows:
        res = r.get("resolved")
        log.info("%-4s %-3d %+-4d %-3d %-18s %s %s %s", r["set"], r["I"], r["rel"], r["tile"][1], tuple(r["lb"][1:]), r["status"],
                 (res["dir"], res["idx"], res["dx"], res["dy"]) if res else "", r.get("why") or [(c["dir"], c["idx"], c["dx"], c["fits"][:6]) for c in r.get("cands", ()) if c["fits"]])
    if a.record:
        commit = E.git_head(REPO)
        with db.engine().begin() as conn:
            E.ensure_family(conn, "cycloneiv")
            for r in rows:
                if "on" not in r or not r.get("honoured"):
                    continue
                nme, bnm = R.spec_name(r), N.base_name(r)
                bid = H.register_build(conn, bnm, "r4 rowparity base")
                sid = H.register_build(conn, nme, "r4 rowparity forced single path")
                meta = {"group": "r4_rowparity", "tile": r["tile"], "I": r["I"], "lb": r["lb"], "rel": r["rel"], "set": r["set"],
                        "table": r["table"], "status": r["status"], "plane_level": True, "evidence_level": "set",
                        "record": (lambda c: [c["dir"], c["idx"], c["dx"], c["dy"]] if c else None)(r.get("resolved")),
                        "fits": [(c["dir"], c["idx"], c["dx"], c["dy"], c["fits"]) for c in r["cands"] if c["fits"]]}
                E.record_specimen(conn, "cycloneiv", "EP4CGX150", nme, bnm, r["on"], r["off"], meta, "r4_rowparity:R4",
                                  "scripts/cycloneiv_r4_rowparity.py", commit, H.NV, tool_version="25.1", build_base=bid, build_spec=sid)
        log.info("evidence rows recorded")
    grp = collections.defaultdict(list)
    for r in rows:
        if r.get("resolved") and r["set"] == 1:
            c = r["resolved"]
            grp[(r["I"], r["rel"], r["tile"][1] % 2)].append((r["tile"][1], (c["dir"], c["idx"], c["dx"], c["dy"])))
    for k, v in sorted(grp.items()):
        log.info("set1 (I, rel, parity) %s: %s -> %s", k, sorted(v), "CONSISTENT" if len({x[1] for x in v}) == 1 else "MISS: same-parity rows differ")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("avail", "plan", "analyse"))
    ap.add_argument("--out")
    ap.add_argument("--plan")
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_r4_rowparity.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
