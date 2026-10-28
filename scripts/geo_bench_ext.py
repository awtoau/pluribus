#!/usr/bin/env python3.15t
"""Geo investigation, extension benches in `pluribus_geo_scratch` (postgis, pgrouting, vector).

  python3.15t scripts/geo_bench_ext.py --stage postgis|routing|vector
Needs tmp/geo/tiles.json + luts.npy (geo_tiles.py), tmp/ddb/stingray4_rt_fanout.npz, tmp/cycloneiv/vo/*.vo,
evidence/cycloneiv/cycloneiv_forced_lab*.json.  Results tmp/geo/bench_ext_<stage>.json, log tmp/logs/geo_bench_ext.log.
psql CLI over the unix socket (scratch use).  Per-statement stall limit: statement_timeout 180s (cold worst case seen: 4 s).
"""
import argparse
import glob
import json
import logging
import re
import statistics
import subprocess
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
GEO = REPO / "tmp/geo"
log = logging.getLogger("geo_bench_ext")
PSQL = ["psql", "-X", "-q", "-At", "-h", "/run/postgresql", "-d", "pluribus_geo_scratch", "-v", "ON_ERROR_STOP=1"]
LIMIT = "set statement_timeout='180s';"


def q(sql):
    r = subprocess.run(PSQL + ["-c", LIMIT + sql], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout.strip()


def tm(sql, pre=""):
    """ms of one statement (psql \\timing, excludes process start); pre = session settings run first"""
    r = subprocess.run(PSQL + ["-c", LIMIT + pre, "-c", "\\timing on", "-c", sql], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return float(re.findall(r"Time: ([0-9.]+) ms", r.stdout)[-1])


def med(sql, n=7, pre=""):
    return round(statistics.median(tm(sql, pre) for _ in range(n)), 3)


def medf(fn, n=7):
    t = []
    for _ in range(n):
        s = time.perf_counter(); fn(); t.append((time.perf_counter() - s) * 1000)
    return round(statistics.median(t), 3)


def copy(table, path):
    subprocess.run(PSQL + ["-c", f"\\copy {table} from '{path}' csv"], check=True)


# ---------------------------------------------------------------- postgis
def postgis():
    T = json.load(open(GEO / "tiles.json"))["tiles"]
    X = np.array([t["x"] for t in T]); Y = np.array([t["y"] for t in T]); S = np.array([t["set"] for t in T])
    csv = GEO / "tiles.csv"
    csv.write_text("".join(f"{t['x']},{t['y']},{t['kind']},{t['tier']},{t['cells']},{t['ver']},{t['set']},{t['edge']}\n" for t in T))
    q("drop table if exists tiles; create table tiles(x int,y int,kind text,tier text,cells int,ver int,\"set\" int,edge int)")
    copy("tiles", csv)
    t0 = time.perf_counter()
    q("alter table tiles add column pt geometry(Point), add column geom geometry(Polygon); "
      "update tiles set pt=ST_MakePoint(x,y), geom=ST_MakeEnvelope(x,y,x+1,y+1); "
      "create index tiles_pt on tiles using gist(pt); create index tiles_geom on tiles using gist(geom); "
      "create index tiles_bt on tiles(x,y); analyze tiles")
    R = {"tiles": len(T), "build_geometry_gist_s": round(time.perf_counter() - t0, 2)}
    scopes = [(5, 5, 20, 30), (60, 40, 75, 55), (100, 70, 116, 90)]
    env = ",".join(f"ST_MakeEnvelope({a},{b},{c},{d})" for a, b, c, d in scopes)
    R["scope_union_st_union_intersects_ms"] = med(f"select count(*), sum(\"set\") from tiles where ST_Intersects(pt, (select ST_Union(array[{env}])))")
    R["scope_union_or_envelopes_ms"] = med("select count(*), sum(\"set\") from tiles where " + " or ".join(
        f"pt && ST_MakeEnvelope({a},{b},{c},{d})" for a, b, c, d in scopes))
    def np_scope():
        m = np.zeros(len(T), bool)
        for a, b, c, d in scopes:
            m |= (X >= a) & (X <= c) & (Y >= b) & (Y <= d)
        return int(m.sum()), int(S[m].sum())
    R["scope_union_numpy_ms"] = medf(np_scope, 100)
    R["scope_answers_agree"] = q(f"select count(*)||','||sum(\"set\") from tiles where ST_Intersects(pt,(select ST_Union(array[{env}])))") == "%d,%d" % np_scope()
    # edge tiles
    q("drop table if exists die; create table die as select ST_Union(geom) g from tiles")
    R["edge_boundary_intersects_ms"] = med("select count(*) from tiles where ST_Intersects(geom,(select ST_Boundary(g) from die))")
    R["edge_touches_ms"] = med("select count(*) from tiles, die where ST_Touches(tiles.geom, ST_Difference(die.g, ST_Buffer(ST_Boundary(die.g), 0.5)))")
    R["edge_tiles_by_boundary"] = int(q("select count(*) from tiles where ST_Intersects(geom,(select ST_Boundary(g) from die))"))
    R["edge_tiles_by_column"] = int(q("select count(*) from tiles where edge=1"))
    # neighbours
    rng = np.random.default_rng(1)
    pts = [(int(T[i]["x"]), int(T[i]["y"])) for i in rng.integers(0, len(T), 1000)]
    vals = ",".join(f"({x},{y})" for x, y in pts)
    R["neighbours_1000_gist_ms"] = med(f"select count(*) from (values {vals}) v(x,y) join tiles t on ST_Intersects(t.pt, ST_MakeEnvelope(v.x-1,v.y-1,v.x+1,v.y+1)) and (t.x,t.y)<>(v.x,v.y)")
    R["neighbours_1000_st_dwithin_ms"] = med(f"select count(*) from (values {vals}) v(x,y) join tiles t on ST_DWithin(t.pt, ST_MakePoint(v.x,v.y), 1.5) and (t.x,t.y)<>(v.x,v.y)")
    R["neighbours_1000_btree_ms"] = med(f"select count(*) from (values {vals}) v(x,y) join tiles t on t.x between v.x-1 and v.x+1 and t.y between v.y-1 and v.y+1 and (t.x,t.y)<>(v.x,v.y)")
    grid = -np.ones((118, 92), np.int32); grid[X, Y] = np.arange(len(T))
    def np_nb():
        n = 0
        for x, y in pts:
            n += int((grid[max(x - 1, 0):x + 2, max(y - 1, 0):y + 2] >= 0).sum()) - 1
        return n
    R["neighbours_1000_numpy_ms"] = medf(np_nb, 15)
    R["neighbours_counts"] = [int(q(f"select count(*) from (values {vals}) v(x,y) join tiles t on ST_Intersects(t.pt, ST_MakeEnvelope(v.x-1,v.y-1,v.x+1,v.y+1)) and (t.x,t.y)<>(v.x,v.y)")), np_nb()]
    # column bands, region union
    R["colband_group_ms"] = med("select x, sum(\"set\") from tiles group by x")
    R["colband_numpy_ms"] = medf(lambda: np.bincount(X, S, 118), 100)
    R["union_by_kind_ms"] = med("select kind, ST_Area(ST_Union(geom)), ST_NumGeometries(ST_Union(geom)) from tiles group by kind")
    R["union_by_kind"] = q("select string_agg(kind||':'||ST_Area(u)||'/'||ST_NumGeometries(u), ' ') from (select kind, ST_Union(geom) u from tiles group by kind) z")
    # refuted-claim-style point sets: 3 synthetic blobs + 60 noise points on the grid
    rp = []
    for cx, cy in ((15, 20), (70, 50), (105, 80)):
        rp += [(int(np.clip(rng.normal(cx, 2), 0, 117)), int(np.clip(rng.normal(cy, 2), 0, 91))) for _ in range(80)]
    rp += [(int(rng.integers(0, 118)), int(rng.integers(0, 92))) for _ in range(60)]
    q("drop table if exists claims; create table claims(id serial, x int, y int)")
    q("insert into claims(x,y) values " + ",".join(f"({x},{y})" for x, y in rp))
    R["dbscan_points"] = len(rp)
    R["dbscan_st_cluster_ms"] = med("select count(distinct c) from (select ST_ClusterDBSCAN(ST_MakePoint(x,y), eps:=3, minpoints:=5) over () c from claims) z where c is not null")
    R["dbscan_clusters"] = int(q("select count(distinct c) from (select ST_ClusterDBSCAN(ST_MakePoint(x,y), eps:=3, minpoints:=5) over () c from claims) z where c is not null"))
    P = np.array(rp, float)
    def np_dbscan():
        d = np.sqrt(((P[:, None] - P[None]) ** 2).sum(2)); core = (d <= 3).sum(1) >= 5
        lab = -np.ones(len(P), int); c = 0
        for i in np.flatnonzero(core):
            if lab[i] >= 0: continue
            st = [i]; lab[i] = c
            while st:
                j = st.pop()
                for k in np.flatnonzero(d[j] <= 3):
                    if lab[k] < 0:
                        lab[k] = c
                        if core[k]: st.append(k)
            c += 1
        return c
    R["dbscan_numpy_ms"] = medf(np_dbscan, 5); R["dbscan_numpy_clusters"] = np_dbscan()
    R["st_convexhull_of_claims_area"] = float(q("select ST_Area(ST_ConvexHull(ST_Collect(ST_MakePoint(x,y)))) from claims"))
    # GeoJSON export
    t0 = time.perf_counter()
    gj = q("select json_build_object('type','FeatureCollection','features',json_agg(json_build_object('type','Feature','geometry',ST_AsGeoJSON(geom)::json,"
           "'properties',json_build_object('x',x,'y',y,'kind',kind,'tier',tier,'set',\"set\",'ver',ver,'cells',cells)))) from tiles")
    R["geojson_export_s"] = round(time.perf_counter() - t0, 3); R["geojson_bytes"] = len(gj)
    (GEO / "die_pg.geojson").write_text(gj)
    R["geojson_features"] = len(json.loads(gj)["features"])
    csv.unlink()
    return R


# ---------------------------------------------------------------- routing
def routing():
    z = np.load(REPO / "tmp/ddb/stingray4_rt_fanout.npz")
    V, tpl, cnt, eoff, offs = z["V"], z["tpl"], z["cnt"], z["eoff"], z["offs"]
    n = len(V)
    has = V > 0
    reps = cnt[tpl[has]].astype(np.int64)
    srcs = np.repeat(np.flatnonzero(has), reps)
    pick = np.repeat(eoff[tpl[has]], reps) + (np.arange(len(srcs)) - np.repeat(np.cumsum(reps) - reps, reps))
    dsts = np.repeat(V[has].astype(np.int64), reps) + offs[pick]
    srcs = srcs.astype(np.int64); dsts = dsts.astype(np.int64)
    m = len(srcs)
    off = np.zeros(n + 1, np.int64); np.cumsum(np.bincount(srcs, minlength=n), out=off[1:])
    R = {"nodes": n, "edges": m}
    csv = GEO / "redges.csv"
    t0 = time.perf_counter()
    with open(csv, "wb") as fh:
        ids = np.arange(1, m + 1, dtype=np.int64)
        for s in range(0, m, 2_000_000):
            np.savetxt(fh, np.stack([ids[s:s + 2_000_000], srcs[s:s + 2_000_000], dsts[s:s + 2_000_000]], 1), fmt="%d", delimiter=",")
    R["csv_write_s"] = round(time.perf_counter() - t0, 1)
    q("drop table if exists redges; create table redges(id bigint, source bigint, target bigint, cost float8 default 1, reverse_cost float8 default -1)")
    t0 = time.perf_counter(); copy("redges(id,source,target)", csv); R["copy_s"] = round(time.perf_counter() - t0, 1)
    csv.unlink()
    t0 = time.perf_counter()
    q("create index redges_s on redges(source); create index redges_t on redges(target); analyze redges")
    R["index_s"] = round(time.perf_counter() - t0, 1)
    R["table_mb"] = int(q("select pg_total_relation_size('redges')/1000000"))
    rng = np.random.default_rng(3)
    cand = np.flatnonzero(np.diff(off) > 0)
    s0 = int(rng.choice(cand, 1000, replace=False)[0])

    def hops(s, k):
        fr = np.array([s]); seen = {s}; lv = {s: 0}
        for d in range(1, k + 1):
            nxt = np.unique(np.concatenate([dsts[off[f]:off[f + 1]] for f in fr.tolist()])) if len(fr) else fr
            nxt = np.array([x for x in nxt.tolist() if x not in seen], np.int64); seen.update(nxt.tolist())
            for x in nxt.tolist(): lv[x] = d
            fr = nxt
        return lv
    lv = hops(s0, 3)
    far = sorted(x for x, d in lv.items() if d == 3)
    tgt = far[len(far) // 2]
    R["khop3_numpy_size"] = len(lv) - 1
    EDG = "select id, source, target, cost, reverse_cost from redges"
    # per-call graph load: dijkstra over full graph, one pair at 3 hops
    R["dijkstra_full_directed_s"] = round(tm(f"select max(agg_cost) from pgr_dijkstra('{EDG}', {s0}, {tgt}, true)") / 1000, 2)
    R["dijkstra_full_cost"] = q(f"select max(agg_cost) from pgr_dijkstra('{EDG}', {s0}, {tgt}, true)")
    R["select_only_full_s"] = round(tm("select count(*) from (select id, source, target, cost, reverse_cost from redges) z") / 1000, 2)
    R["drivingDistance_k3_full_s"] = round(tm(f"select count(*) from pgr_drivingDistance('select id, source, target, cost from redges', {s0}, 3, true)") / 1000, 2)
    R["drivingDistance_k3_nodes"] = int(q(f"select count(*) from pgr_drivingDistance('select id, source, target, cost from redges', {s0}, 3, true)"))
    # fan-in cone: reverse the edge direction in the SQL
    R["drivingDistance_k3_reverse_s"] = round(tm(f"select count(*) from pgr_drivingDistance('select id, target as source, source as target, cost from redges', {s0}, 3, true)") / 1000, 2)
    # restricted edge SQL: per-call graph limited to the 4-hop cone (what a constrained search would pass)
    cone = list(hops(s0, 4));
    q("drop table if exists cone; create table cone as select * from redges where false")
    q("insert into cone select * from redges where source = any(array[" + ",".join(map(str, cone)) + "])")
    R["cone4_nodes"] = len(cone); R["cone4_edges"] = int(q("select count(*) from cone"))
    R["dijkstra_cone_ms"] = med(f"select max(agg_cost) from pgr_dijkstra('select id, source, target, cost, reverse_cost from cone', {s0}, {tgt}, true)", 5)
    R["drivingDistance_k3_cone_ms"] = med(f"select count(*) from pgr_drivingDistance('select id, source, target, cost from cone', {s0}, 3, true)", 5)
    conelist = ",".join(map(str, cone))
    R["dijkstra_edge_sql_restricted_by_index_ms"] = med(f"select max(agg_cost) from pgr_dijkstra('select id, source, target, cost, reverse_cost from redges where source = any(array[{conelist}])', {s0}, {tgt}, true)", 3)
    # same on plain routes
    R["numpy_khop3_ms"] = medf(lambda: hops(s0, 3), 5)
    R["numpy_path3_ms"] = medf(lambda: tgt in hops(s0, 3), 5)
    R["sql_selfjoin_khop3_ms"] = med(f"select count(distinct e3.target) from redges e1 join redges e2 on e2.source=e1.target join redges e3 on e3.source=e2.target where e1.source={s0}", 5)
    # components
    try:
        t = tm("select count(distinct component) from pgr_connectedComponents('select id, source, target, cost, reverse_cost from redges')")
        R["connectedComponents_s"] = round(t / 1000, 1)
        R["connectedComponents_n"] = int(q("select count(distinct component) from pgr_connectedComponents('select id, source, target, cost, reverse_cost from redges')"))
    except RuntimeError as e:
        R["connectedComponents_s"] = "error: " + str(e)[:120]
    # numpy weak components via label propagation (union-find in numpy)
    def np_cc():
        par = np.arange(n)
        for _ in range(60):
            a = np.minimum(par[srcs], par[dsts])
            np.minimum.at(par, srcs, a); np.minimum.at(par, dsts, a)
            par = par[par]
        return len(np.unique(par[np.unique(np.concatenate([srcs, dsts]))]))
    t0 = time.perf_counter(); R["numpy_cc_components_approx"] = np_cc(); R["numpy_cc_s"] = round(time.perf_counter() - t0, 1)
    return R


# ---------------------------------------------------------------- vector
def hexmasks():
    files = sorted(glob.glob(str(REPO / "tmp/cycloneiv/vo/gx150_*.vo")))
    out = []
    for f in files:
        out.append(np.array([int(m, 16) for m in re.findall(r"lut_mask = 16'h([0-9A-Fa-f]+);", Path(f).read_text(errors="ignore"))], np.uint16))
    return files, out


def vec(row, d):
    return "[" + ",".join(str(int(b)) for b in row) + "]"


def vector():
    R = {}
    rng = np.random.default_rng(5)
    files, masks = hexmasks()
    R["vo_designs"] = len(files); R["vo_luts"] = int(sum(len(m) for m in masks))
    tr = np.concatenate(masks[0::2]); te_all = np.concatenate(masks[1::2])
    R["train_luts"] = int(len(tr)); R["test_pool"] = int(len(te_all))
    # ---- masked-bit prediction: known = low 12 bits, hidden = high 4 bits. train = even designs, test = odd designs
    known = np.uint16(0x0FFF)
    test = rng.choice(te_all, 2000, replace=False)
    truth = (test >> 12).astype(int)
    q("create extension if not exists vector")
    def run_pred(trn, label):
        tk = trn & known; th = trn >> 12
        uk, inv = np.unique(tk, return_inverse=True)
        hid = np.zeros((len(uk), 16), np.int64); np.add.at(hid, (inv, th), 1)
        best_h = hid.argmax(1)
        prior = int(np.bincount(th, minlength=16).argmax())
        ex = {int(k): i for i, k in enumerate(uk)}
        exact = np.array([ex.get(int(t & known), -1) for t in test])
        P = {"train_luts": int(len(trn)), "train_distinct_known12": int(len(uk)), "dictionary_coverage": round(float((exact >= 0).mean()), 3),
             "prior_acc": round(float((truth == prior).mean()), 3),
             "dictionary_acc_all_prior_fallback": round(float((np.where(exact >= 0, best_h[np.maximum(exact, 0)], prior) == truth).mean()), 3)}
        q("drop table if exists kn; create table kn(id int primary key, v vector(16), b bit(16), h int)")
        with open(GEO / "kn.csv", "w") as fh:
            for i, k in enumerate(uk):
                bl = [(int(k) >> j) & 1 for j in range(16)]
                fh.write(f"{i},\"{vec(bl, 16)}\",{''.join(map(str, bl))},{int(best_h[i])}\n")
        copy("kn", GEO / "kn.csv"); q("analyze kn")
        miss = exact < 0
        for name, op in (("l2", "<->"), ("cosine", "<=>"), ("l1", "<+>"), ("hamming_bit", "<~>")):
            col = "b" if name == "hamming_bit" else "v"
            vals = []
            for i, t in enumerate(test):
                bl = [(int(t & known) >> j) & 1 for j in range(16)]
                lit = f"'{vec(bl, 16)}'::vector" if col == "v" else "B'" + "".join(map(str, bl)) + "'"
                vals.append(f"({i},{lit})")
            out = q(f"select z.i, (select h from kn order by {col} {op} z.qv, id limit 1) from (values {','.join(vals)}) z(i, qv)")
            pr = {int(a): int(b) for a, b in (ln.split("|") for ln in out.splitlines())}
            ok = np.array([pr[i] == truth[i] for i in range(len(test))])
            P[f"{name}_acc_all"] = round(float(ok.mean()), 3)
            P[f"{name}_acc_on_dict_miss"] = round(float(ok[miss].mean()), 3) if miss.any() else None
        # same with the dictionary where it hits and NN elsewhere is identical to NN (NN returns the exact pattern at distance 0)
        P["dict_miss_count"] = int(miss.sum())
        def np_pred():
            return np.array([best_h[int(np.bitwise_count(uk ^ (t & known)).argmin())] for t in test])
        npp = np_pred()
        P["numpy_hamming_acc_all"] = round(float((npp == truth).mean()), 3)
        P["numpy_hamming_acc_on_dict_miss"] = round(float((npp == truth)[miss].mean()), 3) if miss.any() else None
        R["pred_" + label] = P
        log.info("pred %s %s", label, P)
    ordr = np.argsort([len(m) for m in masks[0::2]])
    run_pred(tr, "train_all_even_designs")
    run_pred(np.concatenate(masks[0::2][:5]), "train_5_designs")
    one = masks[0::2][int(ordr[len(ordr) // 2])]
    run_pred(one, "train_1_design")
    run_pred(one[:200], "train_200_luts")

    # ---- LAB-level vector(256): real (1 design) + synthetic scale (16 real INITs per LAB) for index latency/recall
    L = np.load(GEO / "luts.npy"); real = L[(L != 0).any(1)]
    NS = 100_000
    pool = tr
    syn = pool[rng.integers(0, len(pool), (NS, 16))].astype(np.uint16)
    labs = np.concatenate([real, syn])
    bits = np.unpackbits(labs.view(np.uint8).reshape(len(labs), 32), axis=1)
    R["lab_vectors"] = len(labs); R["lab_real"] = len(real); R["lab_synthetic"] = NS
    q("drop table if exists lab; create table lab(id int primary key, v vector(256), b bit(256))")
    with open(GEO / "lab.csv", "w") as fh:
        for i, row in enumerate(bits):
            fh.write(f"{i},\"[{','.join(map(str, row))}]\",{''.join(map(str, row))}\n")
    t0 = time.perf_counter(); copy("lab", GEO / "lab.csv"); R["lab_copy_s"] = round(time.perf_counter() - t0, 1)
    (GEO / "lab.csv").unlink(); q("analyze lab")
    R["lab_table_mb"] = int(q("select pg_total_relation_size('lab')/1000000"))
    qid = rng.integers(0, len(labs), 100)
    ids = ",".join(map(str, qid.tolist()))
    K = 10
    def truth_dist(col, op):
        return q(f"set enable_indexscan=off; set enable_bitmapscan=off; select z.id, (select string_agg(d::text, ',' order by d) from (select {col} {op} z.{col} d from lab order by {col} {op} z.{col} limit {K}) y) from lab z where z.id in ({ids})")
    for name, col, op, opclass in (("l2", "v", "<->", "vector_l2_ops"), ("cosine", "v", "<=>", "vector_cosine_ops"), ("hamming_bit", "b", "<~>", "bit_hamming_ops")):
        gt = {int(a): [float(x) for x in b.split(",")] for a, b in (l.split("|") for l in truth_dist(col, op).splitlines())}
        q("drop index if exists lab_idx")
        exact_ms = med(f"select count(*) from (select id from lab order by {col} {op} (select {col} from lab where id={int(qid[0])}) limit {K}) z", 5)
        R[f"{name}_exact_1q_ms"] = exact_ms
        for idx in ("hnsw", "ivfflat"):
            q("drop index if exists lab_idx")
            t0 = time.perf_counter()
            with_ = "(m=16, ef_construction=64)" if idx == "hnsw" else "(lists=316)"
            q(f"create index lab_idx on lab using {idx} ({col} {opclass}) with {with_}")
            bt = round(time.perf_counter() - t0, 1); sz = int(q("select pg_relation_size('lab_idx')/1000000"))
            param = "set hnsw.ef_search=100;" if idx == "hnsw" else "set ivfflat.probes=10;"
            lat = []; rec = []
            for i in qid.tolist()[:100]:
                lat.append(tm(f"select id from lab order by {col} {op} (select {col} from lab where id={i}) limit {K}", param))
                out = q(f"{param} select ({col} {op} (select {col} from lab where id={i})) from lab order by {col} {op} (select {col} from lab where id={i}) limit {K}")
                got = sorted(float(x) for x in out.splitlines() if x)
                tk = gt[i]; kth = tk[-1]
                rec.append(sum(1 for g in got if g <= kth + 1e-9) / K)
            R[f"{name}_{idx}"] = {"build_s": bt, "size_mb": sz, "latency_ms_median_server": round(statistics.median(lat), 1), "recall_at_10": round(float(np.mean(rec)), 3)}
            log.info("%s %s %s", name, idx, R[f"{name}_{idx}"])
    # baseline latency for psql round trip and numpy exact over the same data
    packed = np.packbits(bits, axis=1)
    def np_one():
        d = np.bitwise_count(packed ^ packed[int(qid[0])]).sum(1); return np.argpartition(d, K)[:K]
    R["numpy_hamming_exact_1q_ms"] = medf(np_one, 20)
    R["psql_roundtrip_ms"] = round(statistics.median([tm("select 1") for _ in range(10)]), 2)

    # ---- specimen diffs: bit sets over the union of their keys
    sets = []
    for f in ("cycloneiv_forced_lab", "cycloneiv_forced_lab_58x30", "cycloneiv_forced_lab_37x60", "cycloneiv_forced_lab_100x75"):
        d = json.load(open(REPO / "evidence/cycloneiv" / f"{f}.json"))
        sets += [(k, v["src"], v["snk"], set(v["on"])) for k, v in d.items()]
    keys = sorted(set().union(*[s[3] for s in sets])); kix = {k: i for i, k in enumerate(keys)}
    R["specimen_sets"] = len(sets); R["specimen_dims"] = len(keys)
    if len(keys) <= 2000:
        M = np.zeros((len(sets), len(keys)), np.int8)
        for i, s in enumerate(sets):
            for k in s[3]: M[i, kix[k]] = 1
        q(f"drop table if exists spec; create table spec(id int primary key, src int, snk int, v vector({len(keys)}))")
        with open(GEO / "spec.csv", "w") as fh:
            for i, s in enumerate(sets):
                fh.write(f"{i},{s[1]},{s[2]},\"[{','.join(map(str, M[i]))}]\"\n")
        copy("spec", GEO / "spec.csv"); (GEO / "spec.csv").unlink()
        for name, op in (("l2", "<->"), ("cosine", "<=>")):
            out = q(f"select a.src=b.src, a.snk=b.snk from spec a, lateral (select src, snk from spec c where c.id<>a.id order by c.v {op} a.v, c.id limit 1) b")
            rows_ = [l.split("|") for l in out.splitlines()]
            R[f"specimen_nn_{name}_same_src"] = sum(r[0] == "t" for r in rows_); R[f"specimen_nn_{name}_same_snk"] = sum(r[1] == "t" for r in rows_)
        q("create index spec_h on spec using hnsw (v vector_l2_ops)")
        R["specimen_hnsw_ok"] = True
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["postgis", "routing", "vector"])
    a = ap.parse_args()
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/geo_bench_ext.log", "a")])
    R = {"postgis": postgis, "routing": routing, "vector": vector}[a.stage]()
    json.dump(R, open(GEO / f"bench_ext_{a.stage}.json", "w"), indent=1)
    log.info("%s %s", a.stage, json.dumps(R, indent=1))


if __name__ == "__main__":
    main()
