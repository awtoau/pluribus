#!/usr/bin/env python3
"""Pluribus — parallel all-net reachability with shared cache.

Run with python3.14t (free-threaded / NoGIL).  pg8000 is pure Python — no C
extension ever loads, so the GIL stays disabled throughout.

Architecture
------------
Workers pull nets from a shared queue.  As each worker completes BFS from a
net, it stores the result in a global reach_cache dict.  Subsequent workers
that encounter a net already in the cache can extend their own BFS using the
cached downstream reach instead of re-traversing — this is memoised BFS: once
a net's downstream is known, every upstream net reuses it in O(1) per cache
hit instead of re-expanding the full subtree.

One BFS pass with no stop conditions — full transitive closure.  Queries that
want combinational cones or pad-to-pad paths filter at read time by joining
against ffs / pad_map / ebr_ports.

Usage
-----
  python3.14t fpga/pluribus/reach.py [--bitstream V07] [--workers 24]
"""

import argparse
import queue
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import connect_pg8000, die

MAX_DEPTH = 100000  # no practical limit; die on cycle if BFS depth exceeds this
N_WORKERS = 24

def load_graph(bs_id):
    """Pull fanout from DB into plain Python dicts."""
    conn = connect_pg8000()
    rows = conn.run(
        "SELECT net, cell_type, pin, out_net FROM net_fanout WHERE bitstream=:bs",
        bs=bs_id
    )
    fwd = defaultdict(list)
    for net, ctype, pin, out_net in rows:
        fwd[net].append((ctype, pin, out_net))

    all_nets = [r[0] for r in conn.run(
        "SELECT name FROM nets WHERE bitstream=:bs", bs=bs_id)]

    conn.close()
    return fwd, all_nets



class CountedLock:
    """threading.Lock wrapper that counts acquisitions, contentions, and wait time."""
    def __init__(self, name: str):
        self.name        = name
        self._lock       = threading.Lock()
        self.acquires    = 0
        self.contentions = 0
        self.wait_s      = 0.0

    def acquire(self, blocking=True, timeout=-1):
        if self._lock.acquire(blocking=False):
            self.acquires += 1
            return True
        self.contentions += 1
        t = time.perf_counter()
        result = self._lock.acquire(blocking=blocking, timeout=timeout)
        self.wait_s += time.perf_counter() - t
        if result:
            self.acquires += 1
        return result

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()

    def stats(self) -> str:
        pct = (self.contentions / self.acquires * 100) if self.acquires else 0
        return (f"{self.name}: {self.acquires} acq  "
                f"{self.contentions} contended ({pct:.1f}%)  "
                f"wait={self.wait_s*1000:.1f}ms")


_CYCLE_LIMIT = 10000  # if BFS reaches this depth, something is cyclically wrong

def bfs_one(start, fwd, depth):
    """BFS from start — full transitive closure.

    Plain BFS with no memoisation shortcutting.  The previous ext_cache
    optimisation was removed because merging cached downstream results into
    vis without re-adding them to the frontier prevented deep chains from
    being discovered (cached nets' own fanout was never expanded).

    Cycle detection: vis dict prevents re-visiting any net, so cyclic fanout
    entries (if any) are visited exactly once at minimum hop count.  If BFS
    somehow reaches _CYCLE_LIMIT hops the process dies loudly so the bug is
    not silently swallowed.

    Returns {dst: min_hops}.
    """
    vis = {}
    frontier = {start}

    for d in range(1, depth + 1):
        if d > _CYCLE_LIMIT:
            raise RuntimeError(
                f"bfs_one: depth {d} exceeded _CYCLE_LIMIT={_CYCLE_LIMIT} "
                f"starting from {start!r} — likely a cycle in fwd graph"
            )
        nxt = set()
        for net in frontier:
            for _ctype, _pin, out_net in fwd.get(net, []):
                if not out_net or out_net.startswith("1'b") or out_net in vis:
                    continue
                vis[out_net] = d
                nxt.add(out_net)

        frontier = nxt
        if not frontier:
            break

    return vis


def worker(work_q, fwd, depth, bs_id,
           counters, counters_lock, error_event, total,
           result_buf, result_lock):
    """BFS worker — accumulates results in shared result_buf (no DB writes)."""
    try:
        while True:
            try:
                src = work_q.get(block=True, timeout=0.2)
            except queue.Empty:
                break

            try:
                result = bfs_one(src, fwd, depth)

                if result:
                    rows = [(bs_id, src, dst, h) for dst, h in result.items()]
                    with result_lock:
                        result_buf.extend(rows)

                with counters_lock:
                    counters[0] += 1
                    counters[1] += len(result)
                    n = counters[0]
                    if n % 100 == 0 or n == total:
                        print(
                            f"  {n}/{total} nets  {counters[1]} pairs",
                            end="\r", flush=True
                        )
            finally:
                work_q.task_done()

    except Exception as exc:
        error_event.set()
        print(f"\nFATAL: worker thread died: {exc}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="Parallel all-net BFS into fpga_re.reachability"
    )
    ap.add_argument("--bitstream", default="V07")
    ap.add_argument("--depth",   type=int, default=MAX_DEPTH)
    ap.add_argument("--workers", type=int, default=N_WORKERS)
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    print(f"NoGIL: {not sys._is_gil_enabled()}  "
          f"(workers={args.workers}, depth={args.depth})")

    conn = connect_pg8000()
    row = conn.run("SELECT id FROM bitstreams WHERE label=:l", l=args.bitstream)
    if not row:
        die(f"Bitstream {args.bitstream!r} not found — run load.py first")
    bs_id = row[0][0]

    if args.replace:
        conn.run("DELETE FROM reachability     WHERE bitstream=:bs", bs=bs_id)
        conn.run("DELETE FROM pad_ff_influence WHERE bitstream=:bs", bs=bs_id)
        print(f"Cleared reachability + pad_ff_influence for bitstream {bs_id}")

    conn.close()

    t0 = time.time()
    print("Loading graph…")
    fwd, all_nets = load_graph(bs_id)
    print(f"  {len(all_nets)} nets  {sum(len(v) for v in fwd.values())} edges  "
          f"({time.time()-t0:.1f}s)")

    work_q = queue.Queue()
    for n in all_nets:
        work_q.put(n)
    total = len(all_nets)

    t1 = time.time()
    print(f"\nBFS ({args.workers} threads)…")
    counters      = [0, 0]   # [nets_done, pairs]
    counters_lock = CountedLock("counters_lock")
    error_event   = threading.Event()

    result_buf  = []
    result_lock = CountedLock("result_lock")

    threads = [
        threading.Thread(
            target=worker,
            args=(work_q, fwd, args.depth,
                  bs_id, counters, counters_lock, error_event, total,
                  result_buf, result_lock),
            daemon=True,
            name=f"w{i}"
        )
        for i in range(args.workers)
    ]
    for t in threads: t.start()
    work_q.join()

    if error_event.is_set():
        die("One or more BFS worker threads failed — see FATAL lines above")

    bfs_s = time.time() - t1
    print(f"\n  BFS done in {bfs_s:.1f}s  ({len(result_buf)} pairs in RAM)")
    print(f"  Lock stats:  {counters_lock.stats()}")
    print(f"               {result_lock.stats()}")

    # Bulk-insert all reachability pairs in one COPY operation
    print("Bulk inserting reachability…")
    t_ins = time.time()
    conn = connect_pg8000()
    # Chunk into 100k-row batches to avoid single huge transaction
    CHUNK = 100_000
    for i in range(0, len(result_buf), CHUNK):
        batch = result_buf[i:i + CHUNK]
        vals = ",".join(f"({r[0]},'{r[1]}','{r[2]}',{r[3]})" for r in batch)
        conn.run(
            "INSERT INTO reachability (bitstream,src,dst,min_hops) "
            f"VALUES {vals} "
            "ON CONFLICT (bitstream,src,dst) DO UPDATE SET min_hops=EXCLUDED.min_hops"
        )
    conn.close()
    print(f"  Inserted {len(result_buf)} rows in {time.time()-t_ins:.1f}s")

    # pad→FF influence via JOIN — filter dst to FF data/ce inputs
    # Two passes: (1) direct pad_net→FF.d/ce, (2) pad_net→LUT→FF.d/ce (one LUT level)
    print("Building pad→FF influence…")
    conn = connect_pg8000()
    # Re-fetch bs_id — load.py runs in always-rebuild mode and may have recreated
    # the bitstream row (new id) while the BFS was running above.
    row = conn.run("SELECT id FROM bitstreams WHERE label=:l", l=args.bitstream)
    if not row:
        die(f"Bitstream {args.bitstream!r} disappeared before pad_ff INSERT")
    bs_id = row[0][0]
    # Pass 1: pad net reaches FF D/CE directly. Aggregate MIN to avoid duplicate
    # (bitstream, pad_label, ff_cell) pairs from multiple reachability paths.
    # Re-fetch bs_id immediately before INSERT — load.py always-rebuild mode
    # drops+recreates the bitstream row on every run, so the id can change even
    # between the re-fetch above and this INSERT if a concurrent build ran load.py
    # in the window. Using :bs as the literal bitstream column value (not pm.bitstream
    # from the JOIN) ensures the INSERT row matches the FK that exists right now.
    row = conn.run("SELECT id FROM bitstreams WHERE label=:l", l=args.bitstream)
    if not row:
        die(f"Bitstream {args.bitstream!r} disappeared before pad_ff INSERT")
    bs_id = row[0][0]
    conn.run("""
        INSERT INTO pad_ff_influence (bitstream, pad_label, ff_cell, min_hops)
        SELECT :bs, pm.label, f.cell, MIN(r.min_hops)
        FROM pad_map pm
        JOIN reachability r ON r.bitstream=:bs
                           AND r.src=pm.net_in
        JOIN ffs f ON f.bitstream=:bs
                  AND (f.d=r.dst OR f.ce=r.dst)
        WHERE pm.bitstream=:bs AND pm.net_in IS NOT NULL
        GROUP BY pm.label, f.cell
        ON CONFLICT (bitstream, pad_label, ff_cell) DO UPDATE
            SET min_hops = LEAST(pad_ff_influence.min_hops, EXCLUDED.min_hops)
    """, bs=bs_id)
    # Pass 2 removed: the LUT→FF connection arcs are incomplete in the current
    # extraction — LUT output nets don't appear in net_fanout.net so BFS stops
    # at LUT outputs. The 320 pad_ff rows are from IOLOGIC-direct paths only.
    # TODO: fix load.py arc extraction to cover the full combinational cone.
    r1 = conn.run("SELECT COUNT(*) FROM pad_ff_influence WHERE bitstream=:bs", bs=bs_id)
    print(f"  pad_ff_influence: {r1[0][0]} rows")
    conn.close()

    print(f"\nTotal: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
