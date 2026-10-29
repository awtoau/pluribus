#!/usr/bin/env python3.15t
"""Cyclone IV: LB -> R4 group displacement (dx, df) vs (source column - destination column, destination pitch class) (#162/#161/#160)

QUESTION: decode, from forced specimens + raw config-bit diffs, whether the record dx and asm-group frame shift df of an
LB -> R4 hop are a function of (rel = source LAB X - destination tile X, destination column pitch w(X) = FX[X]-FX[X-1]).

PREDICTION (before any run):
 P1: (dx, df) depend only on (rel, w) -- NOT on the R4 index, record, row, or tile.
     REFUTED by any two resolved arcs with the same (rel, w) giving different (dx, df).
 P2: sources one column right of the group (rel +4; rel +1/+2 never occur in any corpus RCF) fit no candidate only because
     the rigid-shift window (|df| <= 80) excludes them.
     REFUTED if a window up to 140 finds no record, or finds records that differ between two arcs of the same (rel, w).
Evidence level SET (rigid-shift fits of 2-cell groups; weak).  Rows with no fit are data rows, never retried.

  scripts/cycloneiv_r4_relcol.py pool [--rng 80]        # re-read existing results, 0 builds
  scripts/cycloneiv_r4_relcol.py plan --tile 88,40 --rels -1,0,3 [--seed N]
  scripts/cycloneiv_r4_relcol.py build --plan P [--nulls]
  scripts/cycloneiv_r4_relcol.py analyse --plan P [--rng 140] [--namer df|map]
  scripts/cycloneiv_r4_relcol.py table / record
Log tmp/logs/cycloneiv_r4_relcol.log.
"""
import argparse
import collections
import json
import logging
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_hop_specimens as H  # noqa: E402
import cycloneiv_r4_name_map as N  # noqa: E402

TMP = REPO / "tmp" / "hop_specimens"
N.PFX = "gxr4df"          # base names are shared with cycloneiv_r4_df_source.py (same u0/u1 -> same base build)
log = logging.getLogger("cycloneiv_r4_relcol")
NAMER = "df"


def spec_name(a):
    lb = a["lb"]
    return f"gxr4df_s_i{a['I']}_X{a['tile'][0]}Y{a['tile'][1]}_from{lb[1]}_{lb[2]}_{lb[3]}"


def map_spec_name(a):
    return f"gxr4_s_{a['wire'].lower()}{a['I']}_X{a['tile'][0]}Y{a['tile'][1]}"


N.spec_name = spec_name


def pitch(g, X):
    return g.FX[X] - g.FX[X - 1]


def cmd_plan(a):
    ch = N.chains_observed()
    X, Y = (int(v) for v in a.tile.split(","))
    rng = random.Random(a.seed * 100003 + X * 1000 + Y)
    arcs = []
    for rel in (int(v) for v in a.rels.split(",")):
        opts = [(k, sorted(l for l in v[0] if l[1] - X == rel), v[1]) for k, v in ch.items() if (k[1], k[2]) == (X, Y)]
        opts = [o for o in opts if o[1] and any(n[3] in H.LI_PORT for n in o[2])]
        if not opts:
            log.info("tile X%dY%d rel %+d: no corpus-seen chain (data row)", X, Y, rel)
            continue
        k, lbs, lis = rng.choice(sorted(opts, key=lambda o: o[0]))
        lb = rng.choice(lbs)
        li = sorted((n for n in lis if n[3] in H.LI_PORT), key=lambda n: (abs(n[1] - X) + abs(n[2] - Y), n))[0]
        u0 = (lb[1], lb[2], H.n_of_i(lb[3]))
        same = (u0[0], u0[1]) == (li[1], li[2])
        u1 = (li[1], li[2], 6 if not (same and u0[2] == 6) else 8)
        arcs.append({"wire": "R4", "I": k[3], "tile": [X, Y], "lb": list(lb), "wire_name": ["R4", X, Y, k[3]], "li": list(li),
                     "u0": list(u0), "u1": list(u1), "port": H.LI_PORT[li[3]], "rel": rel})
    out = Path(a.out or TMP / f"plan_r4rc_X{X}Y{Y}.json")
    out.write_text(json.dumps({"tile": [X, Y], "arcs": arcs}))
    log.info("plan %s: %d arcs, %d bases => %d builds", out.name, len(arcs), len({N.base_name(x) for x in arcs}),
             len(arcs) + len({N.base_name(x) for x in arcs}))
    for x in arcs:
        log.info("  rel %+d I=%d from %s -> LI %s", x["rel"], x["I"], x["lb"], x["li"][3])


def cmd_build(a):
    N.cmd_build(a)


def cmd_analyse(a):
    global NAMER
    N.shifts_fit.__defaults__ = (a.rng,)
    if a.namer == "map":
        N.spec_name = map_spec_name
    N.cmd_analyse(a)
    N.spec_name = spec_name


def load_rows(rng_note=None):
    """Every analysed row from results_r4map_*/r4df_*/r4rc_* with the candidate fit lists."""
    rows = []
    for f in sorted(TMP.glob("results_r4*.json")):
        for r in json.loads(f.read_text())["rows"]:
            if r.get("status", "").startswith(("resolved", "unresolved")):
                rows.append(dict(r, _file=f.name))
    return rows


def cmd_pool(a):
    import cycloneiv_geom as cg
    g = cg.load("ep4cgx150")
    rows = load_rows()
    key = collections.defaultdict(list)
    for r in rows:
        X = r["tile"][0]
        rel = r["lb"][1] - X
        w = pitch(g, X)
        fits = [(c["dx"], c["idx"], c["fits"][0]) for c in r.get("cands", ()) if c["fits"] and abs(c["fits"][0]) <= a.rng]
        dxdf = sorted({(f[0], f[2]) for f in fits})
        key[(rel, w)].append((r["I"], tuple(r["tile"]), tuple(r["lb"][1:]), r["status"], dxdf, r["_file"]))
    for k in sorted(key):
        log.info("(rel %+d, w %d): %d arcs", k[0], k[1], len(key[k]))
        for x in key[k]:
            log.info("    I=%2d X%dY%d src %s %-16s (dx,df) %s  [%s]", x[0], x[1][0], x[1][1], x[2], x[3], x[4], x[5])
    return key


def cmd_table(a):
    """Rule table: per (rel, w) the (dx, df) of resolved rows; misses = resolved rows differing from the modal value."""
    import cycloneiv_geom as cg
    g = cg.load("ep4cgx150")
    seen = {}
    for r in load_rows():
        seen[(r["tile"][0], r["tile"][1], r["I"], tuple(r["lb"]))] = r      # a re-analysed row replaces the older one (files sorted: rc after df)
    key = collections.defaultdict(list)
    nofit = collections.defaultdict(list)
    for (x, y, i, lb), r in seen.items():
        k = (lb[1] - x, pitch(g, x))
        if r["status"] == "resolved":
            key[k].append(((r["resolved"]["dx"], r["resolved"]["fits"][0]), (x, y), i, r.get("honoured")))
        elif r.get("honoured"):
            nofit[k].append(((x, y), i, r["status"], sorted({(c["dx"], c["fits"][0]) for c in r.get("cands", ()) if c["fits"]})))
    misses = 0
    tiles = set()
    for k in sorted(set(key) | set(nofit)):
        vals = collections.Counter(v[0] for v in key[k])
        modal = vals.most_common(1)[0][0] if vals else None
        miss = [v for v in key[k] if v[0] != modal]
        misses += len(miss)
        tiles |= {v[1] for v in key[k]}
        log.info("(rel %+d, w %d): n=%d resolved, modal (dx,df) %s, counts %s, misses %d, no-fit/ambiguous rows %d", k[0], k[1],
                 len(key[k]), modal, dict(vals), len(miss), len(nofit[k]))
        for m in miss:
            log.info("    MISS %s at X%dY%d I=%d", m[0], m[1][0], m[1][1], m[2])
        for n in nofit[k]:
            log.info("    DATA %s I=%d %s fits %s", n[0], n[1], n[2], n[3])
    log.info("resolved scopes (dest tiles): %d %s; total misses %d", len(tiles), sorted(tiles), misses)


def cmd_record(a):
    import db
    from provenance import evidence_io as E
    commit = E.git_head(REPO)
    n = 0
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        for f in a.plans:
            for r in json.loads(Path(f).read_text())["rows"]:
                if "on" not in r or not r.get("honoured") or not (r.get("status") == "resolved" or r.get("status", "").startswith("unresolved")):
                    continue
                nme = spec_name(r)
                bid = H.register_build(conn, N.base_name(r), "r4 relcol base")
                sid = H.register_build(conn, nme, "r4 relcol forced single path")
                meta = {"group": "r4_relcol", "tile": r["tile"], "I": r["I"], "lb": r["lb"], "rel": r["lb"][1] - r["tile"][0],
                        "honoured": r["honoured"], "status": r["status"], "plane_level": True, "evidence_level": "set",
                        "fits": [(c["dx"], c["idx"], c["fits"]) for c in r.get("cands", ()) if c["fits"]]}
                E.record_specimen(conn, "cycloneiv", "EP4CGX150", nme, N.base_name(r), r["on"], r["off"], meta, "r4_relcol:R4",
                                  "scripts/cycloneiv_r4_relcol.py", commit, H.NV, tool_version="25.1", build_base=bid, build_spec=sid)
                n += 1
    log.info("recorded %d evidence rows", n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("pool", "plan", "build", "analyse", "table", "record"))
    ap.add_argument("--tile", default="47,45")
    ap.add_argument("--rels", default="-1,0,3")
    ap.add_argument("--seed", type=int, default=H.SEED)
    ap.add_argument("--rng", type=int, default=80)
    ap.add_argument("--namer", default="df")
    ap.add_argument("--out", default=None)
    ap.add_argument("--plan", default=None)
    ap.add_argument("--nulls", action="store_true")
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("plans", nargs="*")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_r4_relcol.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    for lg in (N.log, H.log):
        lg.setLevel(logging.INFO)
        for h in log.handlers:
            lg.addHandler(h)
    globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
