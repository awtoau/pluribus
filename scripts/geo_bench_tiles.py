#!/usr/bin/env python3.15t
"""Geo investigation bench (a) tile grid and (c) similarity: PostgreSQL native geometry/bit ops vs SQLite R-tree vs numpy.

  python3.15t scripts/geo_bench_tiles.py          # needs tmp/geo/tiles.json, tmp/geo/luts.npy (geo_tiles.py)
Scratch DB `pluribus_geo_scratch` only (psql CLI over the unix socket; scratch use, the pipeline driver stays pg8000).
Results tmp/geo/bench_tiles.json, log tmp/logs/geo_bench_tiles.log.  PostGIS/pgRouting need a superuser to
CREATE EXTENSION, so only trusted extensions + native types are exercised here.
"""
import json
import logging
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
GEO = REPO / "tmp/geo"
log = logging.getLogger("geo_bench_tiles")
PSQL = ["psql", "-X", "-q", "-h", "/run/postgresql", "-d", "pluribus_geo_scratch", "-v", "ON_ERROR_STOP=1"]


def psql(sql, timing=False):
    r = subprocess.run(PSQL + (["-c", "\\timing on", "-c", sql] if timing else ["-c", sql]),
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    ms = [float(m) for m in re.findall(r"Time: ([0-9.]+) ms", r.stdout)]
    return ms[-1] if timing else r.stdout


def med_pg(sql, n=15):
    return statistics.median(psql(sql, True) for _ in range(n))


def med_fn(fn, n=15):
    t = []
    for _ in range(n):
        s = time.perf_counter(); fn(); t.append((time.perf_counter() - s) * 1000)
    return statistics.median(t)


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/geo_bench_tiles.log", "w")])
    T = json.load(open(GEO / "tiles.json"))["tiles"]
    res = {}
    # ---------------- (a) tile grid ----------------
    csv = GEO / "tiles.csv"
    csv.write_text("".join(f"{t['x']},{t['y']},{t['kind']},{t['tier']},{t['cells']},{t['ver']},{t['set']},{t['edge']}\n" for t in T))
    psql("drop table if exists tiles; create table tiles(x int, y int, kind text, tier text, cells int, ver int, \"set\" int, edge int, bx box);")
    subprocess.run(PSQL + ["-c", "create temp table s(x int,y int,kind text,tier text,cells int,ver int,\"set\" int,edge int)"], check=True)
    # \copy into a real staging table (temp tables do not survive across psql invocations)
    psql("drop table if exists stg; create table stg(x int,y int,kind text,tier text,cells int,ver int,\"set\" int,edge int)")
    subprocess.run(PSQL + ["-c", f"\\copy stg from '{csv}' csv"], check=True)
    psql("insert into tiles select x,y,kind,tier,cells,ver,\"set\",edge, box(point(x,y),point(x,y)) from stg; "
         "drop table stg; create index tiles_gist on tiles using gist(bx); create index tiles_xy on tiles(x,y); analyze tiles")
    scopes = [(5, 5, 20, 30), (60, 40, 75, 55), (100, 70, 116, 90)]      # pattern scope = union of 3 rectangles
    rng = np.random.default_rng(1)
    pts = [(int(t["x"]), int(t["y"])) for t in rng.choice(np.array(T, dtype=object), 1000)]
    X = np.array([t["x"] for t in T]); Y = np.array([t["y"] for t in T]); S = np.array([t["set"] for t in T])
    EDGE = np.array([t["edge"] for t in T])
    sq = sqlite3.connect(":memory:")
    sq.execute("create table t(id integer primary key, x int, y int, s int, e int)")
    sq.executemany("insert into t values(?,?,?,?,?)", [(i, t["x"], t["y"], t["set"], t["edge"]) for i, t in enumerate(T)])
    sq.execute("create virtual table r using rtree(id,x0,x1,y0,y1)")
    sq.executemany("insert into r values(?,?,?,?,?)", [(i, t["x"], t["x"], t["y"], t["y"]) for i, t in enumerate(T)])
    sq.execute("create index txy on t(x,y)")

    pgw = " or ".join(f"bx <@ box(point({a},{b}),point({c},{d}))" for a, b, c, d in scopes)
    r = {}
    r["scope_union_pg_gist"] = med_pg(f"select count(*), sum(\"set\") from tiles where {pgw}")
    sqw = " or ".join(f"(x between {a} and {c} and y between {b} and {d})" for a, b, c, d in scopes)
    r["scope_union_sqlite_btree"] = med_fn(lambda: sq.execute(f"select count(*),sum(s) from t where {sqw}").fetchall())
    rw = " or ".join(f"(r.x0>={a} and r.x1<={c} and r.y0>={b} and r.y1<={d})" for a, b, c, d in scopes)
    r["scope_union_sqlite_rtree"] = med_fn(lambda: sq.execute(f"select count(*),sum(t.s) from r join t on t.id=r.id where {rw}").fetchall())
    def np_scope():
        m = np.zeros(len(T), bool)
        for a, b, c, d in scopes:
            m |= (X >= a) & (X <= c) & (Y >= b) & (Y <= d)
        return int(m.sum()), int(S[m].sum())
    r["scope_union_numpy"] = med_fn(np_scope, 200)
    r["edge_flag_pg_column"] = med_pg("select count(*) from tiles where edge=1")
    r["edge_flag_pg_geometry"] = med_pg("select count(*) from tiles where not (bx <@ box(point(1,1),point(116,90)))")
    r["edge_flag_numpy"] = med_fn(lambda: int(((X == 0) | (X == 117) | (Y == 0) | (Y == 91)).sum()), 200)
    vals = ",".join(f"({x},{y})" for x, y in pts)
    r["neighbours_1000_pg_gist"] = med_pg(f"select count(*) from (values {vals}) q(x,y) join tiles t on t.bx && box(point(q.x-1,q.y-1),point(q.x+1,q.y+1)) and (t.x,t.y)<>(q.x,q.y)")
    r["neighbours_1000_pg_btree"] = med_pg(f"select count(*) from (values {vals}) q(x,y) join tiles t on t.x between q.x-1 and q.x+1 and t.y between q.y-1 and q.y+1 and (t.x,t.y)<>(q.x,q.y)")
    def sq_nb():
        n = 0
        for x, y in pts:
            n += len(sq.execute("select id from t where x between ? and ? and y between ? and ? and not(x=? and y=?)", (x - 1, x + 1, y - 1, y + 1, x, y)).fetchall())
        return n
    r["neighbours_1000_sqlite_btree"] = med_fn(sq_nb, 5)
    grid = -np.ones((118, 92), np.int32)
    grid[X, Y] = np.arange(len(T))
    def np_nb():
        n = 0
        for x, y in pts:
            blk = grid[max(x - 1, 0):x + 2, max(y - 1, 0):y + 2]
            n += int((blk >= 0).sum()) - 1
        return n
    r["neighbours_1000_numpy_grid"] = med_fn(np_nb, 15)
    r["colband_agg_pg"] = med_pg("select x, sum(\"set\"), sum(ver)::float/sum(cells) from tiles group by x order by x")
    r["colband_agg_sqlite"] = med_fn(lambda: sq.execute("select x,sum(s) from t group by x").fetchall())
    r["colband_agg_numpy"] = med_fn(lambda: np.bincount(X, S, 118), 200)
    r["answers_agree"] = (int(psql(f"select count(*) from tiles where {pgw}").split()[2]) == np_scope()[0])
    res["a_tiles"] = {"n_tiles": len(T), **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}}
    log.info("a_tiles %s", json.dumps(res["a_tiles"], indent=1))

    # ---------------- (c) similarity ----------------
    L = np.load(GEO / "luts.npy")                  # LAB x 16 LE x u16
    nl = len(L)
    bits = np.unpackbits(L.view(np.uint8).reshape(nl, 32), axis=1)           # 256 bits per LAB
    packed = np.packbits(bits, axis=1)                                      # 32 bytes
    q = np.where((L != 0).any(1))[0][:100]      # LABs that carry logic (the rest are all-zero)
    # numpy brute force NN (excluding self)
    def np_nn():
        out = []
        for i in q:
            d = np.bitwise_count(packed ^ packed[i]).sum(1).astype(np.int32)
            d[i] = 9999
            out.append(int(d.min()))
        return out
    t_np = med_fn(np_nn, 5)
    nn_np = np_nn()
    psql("drop table if exists lab_bits; create table lab_bits(id int primary key, v bit(256))")
    sql = "".join(f"{i}\t{''.join(map(str, bits[i]))}\n" for i in range(nl))
    (GEO / "lab_bits.tsv").write_text(sql)
    subprocess.run(PSQL + ["-c", f"\\copy lab_bits from '{GEO / 'lab_bits.tsv'}'"], check=True)
    psql("analyze lab_bits")
    ids = ",".join(map(str, q.tolist()))
    pg_sql = (f"select sum(d), count(*) from (select (select min(bit_count(l.v # q.v)) from lab_bits l "
              f"where l.id<>q.id) d from lab_bits q where q.id in ({ids})) z")
    t_pg = med_pg(pg_sql, 3)
    sim = {"labs": nl, "queries": len(q), "numpy_ms": round(t_np, 1), "pg_bit_seqscan_ms": round(t_pg, 1)}
    # LUT INIT completion: hide k of 16 bits of one LE INIT, predict from known 12
    inits = L.reshape(-1)
    nz = inits[inits != 0]
    vals_, cnt = np.unique(nz, return_counts=True)
    sim["init_distinct_nonzero"] = int(len(vals_)); sim["init_nonzero"] = int(len(nz))
    mask = np.uint16(0x0FFF)                        # known = low 12 bits, hidden = high 4
    test = rng.choice(nz, min(2000, len(nz)), replace=False)
    ok_dict = ok_nn = 0
    for t in test:
        known = int(t & mask)
        # plain dictionary: most frequent INIT among others with identical known bits
        m = (vals_ & mask) == known
        cand = [(c - (1 if v == t else 0), v) for v, c in zip(vals_[m], cnt[m])]
        cand = [(c, v) for c, v in cand if c > 0]
        if cand:
            best = max(cand)[1]
            ok_dict += int((int(best) >> 12) == (int(t) >> 12))
        # NN: nearest INIT by Hamming over known bits, tie -> most frequent
        d = np.bitwise_count((vals_ ^ t) & mask)
        c2 = cnt - (vals_ == t)
        d = np.where(c2 > 0, d, 99)
        j = np.lexsort((-c2, d))[0]
        ok_nn += int((int(vals_[j]) >> 12) == (int(t) >> 12))
    sim["init_hidden4_acc_dict_exact12"] = round(ok_dict / len(test), 3)
    sim["init_hidden4_acc_hamming_nn"] = round(ok_nn / len(test), 3)
    sim["init_hidden4_acc_prior_most_common"] = round(float(np.mean((vals_[cnt.argmax()] >> 12) == (test >> 12))), 3)
    # specimen pair diffs: nearest pair by Jaccard, does it share sink / src?
    F = json.load(open(REPO / "evidence/cycloneiv/cycloneiv_forced_lab.json"))
    names = list(F)
    sets = [set(F[n]["on"]) for n in names]
    same_snk = same_src = n_ = 0
    for i, s in enumerate(sets):
        best, bj = -1, None
        for j, u in enumerate(sets):
            if i != j:
                jac = len(s & u) / len(s | u) if s | u else 0
                if jac > best:
                    best, bj = jac, j
        n_ += 1
        same_snk += F[names[i]]["snk"] == F[names[bj]]["snk"]
        same_src += F[names[i]]["src"] == F[names[bj]]["src"]
    sim["specimen_pairs"] = n_
    sim["specimen_nn_same_src"] = same_src; sim["specimen_nn_same_snk"] = same_snk
    res["c_similarity"] = sim
    log.info("c_similarity %s", json.dumps(sim, indent=1))
    json.dump(res, open(GEO / "bench_tiles.json", "w"), indent=1)


if __name__ == "__main__":
    main()
