#!/usr/bin/env python3
"""Empirical spike (pluribus #41): does immortalizing / deferring the refcount
of the shared hot decode data remove the free-threaded refcount cache-line
contention that flattens intra-bitstream tile-decode parallelism?

SHARED benchmark: N threads each repeatedly decode the SAME bitstream, sharing
one read-only CRAM + one parsed bits.db cache + one tilegrid.  We measure
throughput scaling and per-decode latency vs thread count, under three
treatments:
  * baseline   -- shared objects as-is
  * immortal   -- CRAM + DB + tilegrid immortalized (INCREF/DECREF -> no-op)
  * deferred   -- PyUnstable_Object_EnableDeferredRefcount on the same objects

Does NOT modify decoder source.  Logs to tmp/bench_immortal.<interp>.log.
"""
import ctypes
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

DB_ROOT = os.environ.get(
    "TRELLIS_DBROOT",
    os.path.join(REPO, "tmp/prjtrellis/database"))
BITFILE = os.path.join(
    REPO, "diamond-fuzz/targets/re_efb_00000_S_nc/impl1/fuzz_impl1.bit")
DEVICE = "LCMXO2-1200"
THREAD_COUNTS = [1, 2, 4, 8, 16]

import native_bitstream
import native_tile_decode as ntd

# ---------------------------------------------------------------------------
# refcount levers (offsets verified by tmp/immortal_probe.py on both interps)
# ---------------------------------------------------------------------------
_NONE = id(None)
IMMORTAL_LOCAL = ctypes.c_uint32.from_address(_NONE + 12).value   # 0xffffffff
IMMORTAL_SHARED = ctypes.c_int64.from_address(_NONE + 16).value   # 0
IMMORTAL_SENTINEL = sys.getrefcount(None)

_defer = getattr(ctypes.pythonapi,
                 "PyUnstable_Object_EnableDeferredRefcount", None)
if _defer is not None:
    _defer.argtypes = [ctypes.py_object]
    _defer.restype = ctypes.c_int


def immortalize(obj):
    addr = id(obj)
    ctypes.c_uint32.from_address(addr + 12).value = IMMORTAL_LOCAL
    ctypes.c_int64.from_address(addr + 16).value = IMMORTAL_SHARED


def _walk(obj, action, seen):
    oid = id(obj)
    if oid in seen:
        return
    seen.add(oid)
    action(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk(k, action, seen)
            _walk(v, action, seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for it in obj:
            _walk(it, action, seen)
    elif hasattr(obj, "__slots__"):
        for s in obj.__slots__:
            if hasattr(obj, s):
                _walk(getattr(obj, s), action, seen)
    elif hasattr(obj, "__dict__"):
        _walk(obj.__dict__, action, seen)
    # str/int/bytes/bytearray/bool/None: leaves (action already applied)


def apply_immortal(roots):
    seen = set()
    n = [0]
    def act(o):
        immortalize(o)
        n[0] += 1
    for r in roots:
        _walk(r, act, seen)
    return n[0]


def apply_deferred(roots):
    seen = set()
    ok = [0]
    tot = [0]
    def act(o):
        if _defer is None:
            return
        tot[0] += 1
        # only container/heap types accept it; skip Nones/ints cheaply is fine
        try:
            ok[0] += _defer(o)
        except Exception:
            pass
    for r in roots:
        _walk(r, act, seen)
    return ok[0], tot[0]


# ---------------------------------------------------------------------------
# load shared state once
# ---------------------------------------------------------------------------
def load_shared():
    pb = native_bitstream.parse_file(BITFILE)
    tilegrid = ntd.load_tilegrid(DEVICE, DB_ROOT)
    # warm the type cache serially (parse every tile type used)
    for _, meta in tilegrid.items():
        ntd.get_tile_type(meta["type"], DB_ROOT)
    return pb.cram, tilegrid


def decode_once(cram, tilegrid):
    """One full-chip single-threaded decode (the shared unit of work)."""
    return ntd.decode_chip(cram, tilegrid, db_root=DB_ROOT, workers=1)


# ---------------------------------------------------------------------------
# the SHARED multithreaded benchmark
# ---------------------------------------------------------------------------
def run_shared(cram, tilegrid, nthreads, reps):
    """N threads, each does `reps` full-chip decodes on the shared CRAM/DB.
    Returns (throughput_decodes_per_s, median_latency_ms, wall_s)."""
    barrier = threading.Barrier(nthreads)
    latencies = [None] * nthreads

    def worker(tid):
        lat = []
        barrier.wait()
        for _ in range(reps):
            t0 = time.perf_counter()
            decode_once(cram, tilegrid)
            lat.append((time.perf_counter() - t0) * 1e3)
        latencies[tid] = lat

    threads = [threading.Thread(target=worker, args=(i,))
               for i in range(nthreads)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0

    all_lat = [x for lst in latencies for x in lst]
    total = nthreads * reps
    return total / wall, statistics.median(all_lat), wall


def canonical_signature(cram, tilegrid):
    can = ntd.canonical(decode_once(cram, tilegrid))
    # stable hashable summary
    items = []
    for tile in sorted(can):
        c = can[tile]
        items.append((tile, frozenset(c["arcs"]),
                      frozenset(c["words"]), frozenset(c["enums"])))
    return hash(frozenset(items)), sum(len(can[t]["arcs"]) for t in can), \
        sum(len(can[t]["words"]) for t in can), \
        sum(len(can[t]["enums"]) for t in can)


# ---------------------------------------------------------------------------
def main():
    interp = f"{sys.version_info.major}.{sys.version_info.minor}t"
    log = open(os.path.join(HERE, f"bench_immortal.{interp}.log"), "w")

    def emit(*a):
        line = " ".join(str(x) for x in a)
        print(line)
        log.write(line + "\n")
        log.flush()

    emit(f"# interpreter: {sys.version.splitlines()[0]}")
    emit(f"# GIL enabled: {sys._is_gil_enabled() if hasattr(sys, '_is_gil_enabled') else '?'}")
    emit(f"# cpus: {os.cpu_count()}  bitfile: {os.path.basename(BITFILE)}")
    emit(f"# deferred lever available: {_defer is not None}")

    cram, tilegrid = load_shared()
    ntiles = len(tilegrid)
    ntypes = len(ntd._db_cache)
    emit(f"# tiles: {ntiles}  tile-types parsed: {ntypes}")

    # calibrate reps: aim ~2.5 s of single-thread work
    t0 = time.perf_counter()
    sig0 = canonical_signature(cram, tilegrid)
    one = time.perf_counter() - t0
    reps = max(8, int(round(2.5 / one)))
    emit(f"# single-decode ~{one*1e3:.1f} ms  -> reps/thread = {reps}")
    emit(f"# baseline decode signature: hash={sig0[0]} arcs={sig0[1]} "
         f"words={sig0[2]} enums={sig0[3]}")
    emit("")

    def sweep(label):
        emit(f"## {label}")
        emit(f"{'threads':>7} {'thru/s':>10} {'speedup':>8} "
             f"{'med_ms':>8} {'wall_s':>8}")
        base_thru = None
        rows = []
        for n in THREAD_COUNTS:
            thru, med, wall = run_shared(cram, tilegrid, n, reps)
            if base_thru is None:
                base_thru = thru
            sp = thru / base_thru
            emit(f"{n:>7} {thru:>10.2f} {sp:>8.2f}x {med:>8.2f} {wall:>8.2f}")
            rows.append((n, thru, sp, med))
        emit("")
        return rows

    # 1) baseline
    base_rows = sweep("baseline (shared, no refcount treatment)")

    # 2) immortalize shared hot objects
    nimm = apply_immortal([cram, tilegrid, ntd._db_cache])
    emit(f"# immortalized {nimm} distinct shared objects "
         f"(CRAM + tilegrid + parsed bits.db)")
    # correctness after immortalizing
    sig1 = canonical_signature(cram, tilegrid)
    emit(f"# post-immortal decode signature: hash={sig1[0]} arcs={sig1[1]} "
         f"words={sig1[2]} enums={sig1[3]}  "
         f"{'MATCH' if sig1 == sig0 else 'MISMATCH!!'}")
    emit("")
    imm_rows = sweep("immortal (CRAM+DB+tilegrid immortalized)")

    # 3) deferred refcount (applied on top; harmless where immortal already)
    #    Re-load fresh shared state so 'deferred' is measured without the
    #    prior immortalization masking it.
    emit("# --- reloading fresh shared state for deferred-only measurement ---")
    ntd._db_cache.clear()
    cram2, tilegrid2 = load_shared()
    sigd0 = canonical_signature(cram2, tilegrid2)
    okd, totd = apply_deferred([cram2, tilegrid2, ntd._db_cache])
    emit(f"# deferred-refcount enabled on {okd}/{totd} walked objects")
    sigd1 = canonical_signature(cram2, tilegrid2)
    emit(f"# post-deferred signature {'MATCH' if sigd1 == sigd0 else 'MISMATCH!!'}")
    emit("")

    def sweep2(label, c, tg):
        emit(f"## {label}")
        emit(f"{'threads':>7} {'thru/s':>10} {'speedup':>8} "
             f"{'med_ms':>8} {'wall_s':>8}")
        base_thru = None
        rows = []
        for n in THREAD_COUNTS:
            thru, med, wall = run_shared(c, tg, n, reps)
            if base_thru is None:
                base_thru = thru
            emit(f"{n:>7} {thru:>10.2f} {thru/base_thru:>8.2f}x "
                 f"{med:>8.2f} {wall:>8.2f}")
            rows.append((n, thru, thru/base_thru, med))
        emit("")
        return rows

    def_rows = sweep2("deferred (EnableDeferredRefcount on shared objects)",
                      cram2, tilegrid2)

    # summary
    emit("=" * 60)
    emit(f"SUMMARY  interpreter {interp}")
    emit(f"{'N':>3} | {'base sp':>8} {'imm sp':>8} {'defer sp':>8} "
         f"| {'base ms':>8} {'imm ms':>8} {'defer ms':>8}")
    for i, n in enumerate(THREAD_COUNTS):
        emit(f"{n:>3} | {base_rows[i][2]:>7.2f}x {imm_rows[i][2]:>7.2f}x "
             f"{def_rows[i][2]:>7.2f}x | {base_rows[i][3]:>8.2f} "
             f"{imm_rows[i][3]:>8.2f} {def_rows[i][3]:>8.2f}")
    log.close()


if __name__ == "__main__":
    main()
