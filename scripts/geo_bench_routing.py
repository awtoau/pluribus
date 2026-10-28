#!/usr/bin/env python3.15t
"""Geo investigation bench (b): decoded Cyclone IV routing graph in PostgreSQL (plain edge table) vs numpy CSR.

  python3.15t scripts/geo_bench_routing.py [--drop]   # needs tmp/ddb/stingray4_rt_fanout.npz
pgRouting itself is NOT measured: CREATE EXTENSION needs a superuser, unavailable to the agent.  What is measured is
the data path every pgRouting call sits on (edge table + btree on src/dst, recursive/self-join traversal).
Scratch DB `pluribus_geo_scratch` only.  Results tmp/geo/bench_routing.json, log tmp/logs/geo_bench_routing.log.
"""
import argparse
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
log = logging.getLogger("geo_bench_routing")
PSQL = ["psql", "-X", "-q", "-h", "/run/postgresql", "-d", "pluribus_geo_scratch", "-v", "ON_ERROR_STOP=1"]


def psql(sql, timing=False):
    r = subprocess.run(PSQL + (["-c", "\\timing on", "-c", sql] if timing else ["-c", sql]), capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    ms = [float(m) for m in re.findall(r"Time: ([0-9.]+) ms", r.stdout)]
    return (ms[-1], r.stdout) if timing else r.stdout


def med_pg(sql, n=5):
    return statistics.median(psql(sql, True)[0] for _ in range(n))


def med_fn(fn, n=5):
    t = []
    for _ in range(n):
        s = time.perf_counter(); fn(); t.append((time.perf_counter() - s) * 1000)
    return statistics.median(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="store_true", help="drop the edge table afterwards")
    a = ap.parse_args()
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/geo_bench_routing.log", "w")])
    z = np.load(REPO / "tmp/ddb/stingray4_rt_fanout.npz")
    V, tpl, cnt, eoff, offs = z["V"], z["tpl"], z["cnt"], z["eoff"], z["offs"]
    n = len(V)
    t0 = time.perf_counter()
    has = V > 0
    reps = cnt[tpl[has]].astype(np.int64)
    srcs = np.repeat(np.flatnonzero(has), reps)
    pick = np.repeat(eoff[tpl[has]], reps) + (np.arange(len(srcs)) - np.repeat(np.cumsum(reps) - reps, reps))
    dsts = np.repeat(V[has].astype(np.int64), reps) + offs[pick]
    srcs = srcs.astype(np.int32); dsts = dsts.astype(np.int32)
    R = {"nodes": n, "edges": len(srcs), "numpy_expand_s": round(time.perf_counter() - t0, 2)}
    log.info("%s", R)
    # numpy CSR (srcs already sorted ascending)
    t0 = time.perf_counter()
    off = np.zeros(n + 1, np.int64); np.cumsum(np.bincount(srcs, minlength=n), out=off[1:])
    R["numpy_csr_build_s"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    order = np.argsort(dsts, kind="stable"); rsrc = srcs[order]
    roff = np.zeros(n + 1, np.int64); np.cumsum(np.bincount(dsts, minlength=n), out=roff[1:])
    R["numpy_reverse_csr_build_s"] = round(time.perf_counter() - t0, 2)
    R["numpy_mb"] = round((dsts.nbytes + off.nbytes + rsrc.nbytes + roff.nbytes) / 1e6)

    # PG load
    csv = GEO / "edges.csv"
    t0 = time.perf_counter()
    with open(csv, "wb") as fh:
        CH = 2_000_000
        for s in range(0, len(srcs), CH):
            np.savetxt(fh, np.stack([srcs[s:s + CH], dsts[s:s + CH]], 1), fmt="%d", delimiter=",")
    R["csv_write_s"] = round(time.perf_counter() - t0, 1)
    psql("drop table if exists edges; create table edges(src int not null, dst int not null)")
    t0 = time.perf_counter()
    subprocess.run(PSQL + ["-c", f"\\copy edges from '{csv}' csv"], check=True)
    R["pg_copy_s"] = round(time.perf_counter() - t0, 1)
    t0 = time.perf_counter()
    psql("create index edges_src on edges(src); create index edges_dst on edges(dst); analyze edges")
    R["pg_index_s"] = round(time.perf_counter() - t0, 1)
    csv.unlink()
    R["pg_size_mb"] = int(psql("select pg_total_relation_size('edges')/1000000", False).split()[2])
    log.info("%s", R)

    rng = np.random.default_rng(3)
    cand = np.flatnonzero(np.diff(off) > 0)
    S = rng.choice(cand, 1000, replace=False)
    arr = "array[" + ",".join(map(str, S.tolist())) + "]"
    R["fanout_1000_pg"] = med_pg(f"select count(*) from edges e join unnest({arr}) u(n) on e.src=u.n")
    R["fanout_1000_numpy"] = med_fn(lambda: sum(int(off[s + 1] - off[s]) for s in S.tolist()))
    R["fanin_1000_pg"] = med_pg(f"select count(*) from edges e join unnest({arr}) u(n) on e.dst=u.n")
    R["fanin_1000_numpy"] = med_fn(lambda: sum(int(roff[s + 1] - roff[s]) for s in S.tolist()))
    R["fanout_1000_pg_count_agree"] = int(psql(f"select count(*) from edges e join unnest({arr}) u(n) on e.src=u.n").split()[2]) == sum(int(off[s + 1] - off[s]) for s in S.tolist())

    def hops(s, k):
        fr = np.array([s], np.int64)
        seen = {int(s)}
        for _ in range(k):
            nxt = np.unique(np.concatenate([dsts[off[f]:off[f + 1]] for f in fr])) if len(fr) else fr
            nxt = np.array([x for x in nxt.tolist() if x not in seen], np.int64)
            seen.update(nxt.tolist()); fr = nxt
        return seen
    s0 = int(S[0])
    for k in (2, 3):
        joins = " ".join(f"join edges e{i} on e{i}.src=e{i - 1}.dst" for i in range(2, k + 1))
        R[f"khop{k}_reach_size"] = len(hops(s0, k)) - 1
        R[f"khop{k}_pg_selfjoin"] = med_pg(f"select count(distinct e{k}.dst) from edges e1 {joins} where e1.src={s0}", 3)
        R[f"khop{k}_numpy_bfs"] = med_fn(lambda: hops(s0, k), 3)
        R[f"khop{k}_pg_distinct_agrees_ex_start"] = None
    # unweighted shortest path: pick a node exactly 3 hops away
    h2 = hops(s0, 2); h3 = hops(s0, 3) - h2
    t_node = int(sorted(h3)[len(h3) // 2])
    R["sp3_pg_selfjoin_first"] = med_pg(f"select 1 from edges e1 join edges e2 on e2.src=e1.dst join edges e3 on e3.src=e2.dst where e1.src={s0} and e3.dst={t_node} limit 1", 3)
    R["sp3_numpy_bfs"] = med_fn(lambda: t_node in hops(s0, 3), 3)
    # full-graph reachability closure from one source (numpy level BFS) vs PG recursive CTE with UNION
    t0 = time.perf_counter()
    seen = np.zeros(n, bool); seen[s0] = True; fr = np.array([s0])
    lvl = 0
    while len(fr):
        nxt = np.unique(np.concatenate([dsts[off[f]:off[f + 1]] for f in fr.tolist()]))
        nxt = nxt[~seen[nxt]]; seen[nxt] = True; fr = nxt; lvl += 1
    R["closure_numpy_s"] = round(time.perf_counter() - t0, 2); R["closure_size"] = int(seen.sum()); R["closure_levels"] = lvl
    try:
        t, _ = psql(f"set statement_timeout='120s'; with recursive r(n) as (select {s0} union select e.dst from edges e join r on e.src=r.n) select count(*) from r", True)
        R["closure_pg_recursive_s"] = round(t / 1000, 2)
    except RuntimeError as e:
        R["closure_pg_recursive_s"] = "timeout/error: " + str(e).strip()[:80]
    log.info("%s", json.dumps(R, indent=1))
    json.dump(R, open(GEO / "bench_routing.json", "w"), indent=1)
    if a.drop:
        psql("drop table edges")


if __name__ == "__main__":
    main()
