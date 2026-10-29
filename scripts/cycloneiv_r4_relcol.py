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
PREDICTION P1' (frame-distance form, written after the P1 miss at X63Y32, before the sweep): (dx, df) is a function of
 d = FX[src] - FX[dst] and the destination pitch w only.  REFUTED by any two arcs with the same (d, w) giving different (dx, df).
Evidence level SET (rigid-shift fits of 2-cell groups; weak).  Rows with no fit are data rows, never retried.

PREDICTION P3 (per-column enumeration, written before the sweep): for a fixed destination COLUMN X and fixed source relative
 column, (dx, df) is constant across rows Y and across R4 names.  REFUTED by two arcs in the same destination column and the
 same relative source column with different (dx, df); then the rows of that column are enumerated.  Each arc records
 FX[dst-1], FX[dst], FX[dst+1] and the kinds of dst-1 / dst+1; no rule is fitted first.

  scripts/cycloneiv_r4_relcol.py colplan --cols 87,25,88 --rows 2 --rels=-1,0,3,4 --out P
  scripts/cycloneiv_r4_relcol.py coltable
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


_CH = None


def chains():
    global _CH
    if _CH is None:
        _CH = N.chains_observed()
    return _CH


def cmd_plan(a):
    ch = chains()
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


def ctx_of(g, X):
    return {"fx": [int(g.FX[X - 1]), int(g.FX[X]), int(g.FX[X + 1])], "kinds": [g.kind.get(X - 1), g.kind.get(X + 1)]}


def cmd_colplan(a):
    import cycloneiv_geom as cg
    g = cg.load("ep4cgx150")
    ch = chains()
    rels = [int(v) for v in a.rels.split(",")]
    arcs = []
    for X in (int(v) for v in a.cols.split(",")):
        ys = collections.defaultdict(set)
        for (t, x, y, i), (lbs, lis) in ch.items():
            if x == X and 6 <= y <= 77:
                ys[y] |= {l[1] - X for l in lbs} & set(rels)
        order = sorted(ys, key=lambda y: (-len(ys[y]), random.Random(a.seed + X * 131 + y).random()))
        rows = order[:a.rows]
        log.info("column X%d: rows %s rels available %s", X, rows, [sorted(ys[y]) for y in rows])
        for y in rows:
            sub = argparse.Namespace(tile=f"{X},{y}", rels=a.rels, seed=a.seed, out=str(TMP / "_tmp_plan.json"))
            cmd_plan(sub)
            for x in json.loads(Path(sub.out).read_text())["arcs"]:
                arcs.append(dict(x, ctx=ctx_of(g, X)))
    Path(a.out).write_text(json.dumps({"tile": None, "arcs": arcs}))
    log.info("colplan %s: %d arcs, %d bases => %d builds", Path(a.out).name, len(arcs), len({N.base_name(x) for x in arcs}),
             len(arcs) + len({N.base_name(x) for x in arcs}))


def cmd_cellplan(a):
    """Plan one arc per requested (dest X, rel) cell; rows Y already measured for that cell are avoided (second row)."""
    import cycloneiv_geom as cg
    g = cg.load("ep4cgx150")
    ch = chains()
    have = collections.defaultdict(set)
    for r in load_rows():
        have[(r["tile"][0], r["lb"][1] - r["tile"][0])].add(r["tile"][1])
    arcs = []
    for cell in a.cells.split(";"):
        X, rel = (int(v) for v in cell.split(","))
        ys = {y for (t, x, y, i), (lbs, lis) in ch.items() if x == X and 6 <= y <= 77 and any(l[1] - X == rel for l in lbs)} - have[(X, rel)]
        if not ys:
            log.info("cell X%d rel %+d: no corpus-seen chain left (data row)", X, rel)
            continue
        y = random.Random(a.seed + X * 131 + rel * 7).choice(sorted(ys))
        sub = argparse.Namespace(tile=f"{X},{y}", rels=str(rel), seed=a.seed, out=str(TMP / "_tmp_plan.json"))
        cmd_plan(sub)
        arcs += [dict(x, ctx=ctx_of(g, X)) for x in json.loads(Path(sub.out).read_text())["arcs"]]
    Path(a.out).write_text(json.dumps({"tile": None, "arcs": arcs}))
    log.info("cellplan %s: %d arcs, %d bases => %d builds", Path(a.out).name, len(arcs), len({N.base_name(x) for x in arcs}),
             len(arcs) + len({N.base_name(x) for x in arcs}))


def cmd_coltable(a):
    """Measured per-column table: (dest X, rel) -> {(dx, df): rows}; no-fit rows listed as data."""
    import cycloneiv_geom as cg
    g = cg.load("ep4cgx150")
    seen = {}
    for r in load_rows():
        seen[(r["tile"][0], r["tile"][1], r["I"], tuple(r["lb"]))] = r
    tab = collections.defaultdict(lambda: collections.defaultdict(list))
    for (x, y, i, lb), r in seen.items():
        rel = lb[1] - x
        if r["status"] == "resolved":
            tab[(x, rel)][(r["resolved"]["dx"], r["resolved"]["fits"][0])].append((y, i))
        else:
            tab[(x, rel)]["data:" + r["status"]].append((y, i))
    miss = 0
    for k in sorted(tab):
        d = tab[k]
        res = [v for v in d if not str(v[0]).startswith("data")] if False else [v for v in d if isinstance(v, tuple)]
        flag = "MISS" if len(res) > 1 else ""
        miss += bool(flag)
        c = ctx_of(g, k[0])
        log.info("X%-3d rel %+d fx %s kinds %s: %s %s", k[0], k[1], c["fx"], c["kinds"], {str(v): len(rs) for v, rs in d.items()}, flag)
    log.info("columns x rel with >1 distinct (dx, df): %d", miss)
    if a.nulls:      # --nulls doubles as "record the table" here
        import db
        from provenance import evidence_io as E
        table = {f"{k[0]},{k[1]}": {"fx": ctx_of(g, k[0])["fx"], "kinds": ctx_of(g, k[0])["kinds"],
                                    "values": {str(v): [list(r) for r in rs] for v, rs in d.items()}} for k, d in tab.items()}
        n = sum(len(rs) for d in tab.values() for rs in d.values())
        with db.engine().begin() as conn:
            E.ensure_family(conn, "cycloneiv")
            E.record_decode(conn, "cycloneiv", "EP4CGX150", f"R4 per-column (dx, df) table by source rel ({n} arcs)",
                            {"file": table, "meta": {}}, E.git_head(REPO), "scripts/cycloneiv_r4_relcol.py coltable",
                            generator="scripts/cycloneiv_r4_relcol.py", n_objects=n, kind="derived-table")
        log.info("recorded derived-table row, %d arcs", n)


def cmd_build(a):
    N.cmd_build(a)


def cmd_analyse(a):
    global NAMER
    N.shifts_fit.__defaults__ = (a.rng,)
    H.Graph.vx = lambda self, X: self.D.vx_of(X)      # non-LAB destination columns (MUL / M9K): nearest-LAB-left offset, same as the resolver
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


PARENT_TILES = {(47, 45), (30, 50), (89, 44), (63, 32)}      # rows that existed when P1' was written; the rest are confirm rows


def cmd_record(a):
    """Evidence rows (source_ref r4_relcol:R4) for every honoured arc; meta.pred = modal (dx, df) of the PARENT rows at the same
    (d, w), meta.consistent = observed == pred (None = no parent at that key / unresolved).  The claim is built by claims_register.py."""
    import cycloneiv_geom as cg
    import db
    from provenance import evidence_io as E
    g = cg.load("ep4cgx150")
    seen = {}
    for r in load_rows():
        seen[(r["tile"][0], r["tile"][1], r["I"], tuple(r["lb"]))] = r
    key = lambda r: (g.FX[r["lb"][1]] - g.FX[r["tile"][0]], pitch(g, r["tile"][0]))   # noqa: E731
    model = collections.defaultdict(collections.Counter)
    for r in seen.values():
        if tuple(r["tile"]) in PARENT_TILES and r["status"] == "resolved":
            model[key(r)][(r["resolved"]["dx"], r["resolved"]["fits"][0])] += 1
    commit = E.git_head(REPO)
    n = 0
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        for r in seen.values():
            if "on" not in r or not r.get("honoured"):
                continue
            nme = (map_spec_name(r) if r["_file"].startswith("results_r4map") else spec_name(r))
            if not (H.CORPUS / nme / "design.toml").exists():
                continue
            obs = (r["resolved"]["dx"], r["resolved"]["fits"][0]) if r["status"] == "resolved" else None
            pred = model[key(r)].most_common(1)[0][0] if model.get(key(r)) else None
            bnm = N.base_name(r).replace("gxr4df_", "gxr4_", 1) if r["_file"].startswith("results_r4map") else N.base_name(r)
            if not (H.CORPUS / bnm / "design.toml").exists():
                continue
            bid = H.register_build(conn, bnm, "r4 relcol base")
            sid = H.register_build(conn, nme, "r4 relcol forced single path")
            meta = {"group": "r4_relcol", "tile": r["tile"], "I": r["I"], "lb": r["lb"], "d": key(r)[0], "w": key(r)[1],
                    "role": "parent" if tuple(r["tile"]) in PARENT_TILES else "confirm", "observed": obs, "pred": pred,
                    "consistent": (obs == pred) if (obs and pred) else None, "honoured": True, "status": r["status"],
                    "plane_level": True, "evidence_level": "set",
                    "fits": [(c["dx"], c["idx"], c["fits"]) for c in r.get("cands", ()) if c["fits"]]}
            E.record_specimen(conn, "cycloneiv", "EP4CGX150", nme, bnm, r["on"], r["off"], meta, "r4_relcol:R4",
                              "scripts/cycloneiv_r4_relcol.py", commit, H.NV, tool_version="25.1", build_base=bid, build_spec=sid)
            n += 1
    log.info("recorded %d evidence rows", n)


def cmd_colrecord(a):
    """Evidence rows (source_ref r4_col:R4) for the per-column prediction P3: per (dest X, rel) the first resolved row (by Y, I)
    is the parent, every later resolved row is a confirm row (consistent = same (dx, df)) or a refute row.  Singletons: consistent None."""
    import db
    import schema as S
    from sqlalchemy import select, update
    from provenance import evidence_io as E
    seen = {}
    for r in load_rows():
        seen[(r["tile"][0], r["tile"][1], r["I"], tuple(r["lb"]))] = r
    grp = collections.defaultdict(list)
    for r in seen.values():
        if r["status"] == "resolved" and r.get("honoured") and "on" in r:
            grp[(r["tile"][0], r["lb"][1] - r["tile"][0])].append(r)
    commit = E.git_head(REPO)
    n = 0
    import cycloneiv_geom as cg
    g = cg.load("ep4cgx150")
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        for (X, rel), rs in sorted(grp.items()):
            rs.sort(key=lambda r: (r["tile"][1], r["I"], r["lb"]))
            val = lambda r: (r["resolved"]["dx"], r["resolved"]["fits"][0])   # noqa: E731
            par = val(rs[0])
            for j, r in enumerate(rs):
                nme = map_spec_name(r) if r["_file"].startswith("results_r4map") else spec_name(r)
                bnm = N.base_name(r).replace("gxr4df_", "gxr4_", 1) if r["_file"].startswith("results_r4map") else N.base_name(r)
                if not ((H.CORPUS / nme / "design.toml").exists() and (H.CORPUS / bnm / "design.toml").exists()):
                    continue
                bid = H.register_build(conn, bnm, "r4 column base")
                sid = H.register_build(conn, nme, "r4 column forced single path")
                meta = {"group": "r4_col", "tile": r["tile"], "I": r["I"], "lb": r["lb"], "rel": rel, "group_key": f"X{X}/rel{rel}", "col_ctx": ctx_of(g, X),
                        "role": "parent" if j == 0 else "confirm", "observed": val(r), "pred": par,
                        "consistent": (val(r) == par) if len(rs) > 1 else None, "plane_level": True, "evidence_level": "set"}
                eid = E.record_specimen(conn, "cycloneiv", "EP4CGX150", nme, bnm, r["on"], r["off"], meta, "r4_col:R4",
                                        "scripts/cycloneiv_r4_relcol.py", commit, H.NV, tool_version="25.1", build_base=bid, build_spec=sid)
                old = conn.execute(select(S.evidence.c.result).where(S.evidence.c.id == eid)).scalar()
                if old.get("meta", {}).get("group_key") != meta["group_key"]:      # row written before group_key existed
                    conn.execute(update(S.evidence).where(S.evidence.c.id == eid).values(result=dict(old, meta=dict(old["meta"], group_key=meta["group_key"]))))
                n += 1
    log.info("recorded %d per-column evidence rows", n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("cellplan", "colrecord", "colplan", "coltable", "pool", "plan", "build", "analyse", "table", "record"))
    ap.add_argument("--tile", default="47,45")
    ap.add_argument("--rels", default="-1,0,3")
    ap.add_argument("--cols", default="87,25,88")
    ap.add_argument("--cells", default="")
    ap.add_argument("--rows", type=int, default=2)
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
