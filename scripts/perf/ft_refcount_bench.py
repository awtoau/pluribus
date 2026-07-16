#!/usr/bin/env python3
"""Free-threaded refcount-contention benchmark for native tile decode.

Measures intra-bitstream tile-decode thread scaling on whatever interpreter
runs it (python3.14t vs python3.15t).  Two cases:

  SHARED   -- N threads decode the SAME shared CRAM + shared tile-type DB.
              This is the real intra-bitstream case; if it does NOT scale the
              bottleneck is free-threaded refcount contention on shared
              immutable objects (cache-line ping-pong), not the GIL.

  PRIVATE  -- N threads each own a PRIVATE deep copy of CRAM + DB (independent
              data, the "bitstream-level parallelism" control).  Expected to
              scale on any free-threaded build regardless of refcount design.

Work is amplified to R full-chip decodes and split across T threads so
thread/dispatch fixed costs are amortised and we measure the decode compute
scaling itself.  Pure Python hot path -- no pytrellis, no sqlalchemy.

Emits one RESULT line per (case,threads) as `key=value` for easy parsing, plus
a human summary.  Logs to tmp/ft_refcount_bench_<tag>.log.
"""
import os
import sys
import time
import json
import threading

PLURIBUS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(PLURIBUS, "scripts")
DB = os.environ.get("TRELLIS_DBROOT", os.path.join(PLURIBUS, "tmp/prjtrellis/database"))
BIT = os.path.join(PLURIBUS,
    "diamond-fuzz/targets/re_efb_00000_S_nc/impl1/fuzz_impl1.bit")
DEVICE = "LCMXO2-1200"
R = 128          # total full-chip decodes (amortises thread setup)
THREAD_COUNTS = (1, 2, 4, 8, 16)

sys.path.insert(0, SCRIPTS)
import native_bitstream        # noqa: E402
import native_tile_decode as ntd   # noqa: E402


def gil_state():
    f = getattr(sys, "_is_gil_enabled", None)
    return "unknown" if f is None else str(f())


def main():
    tag = "".join(c for c in sys.version.split()[0] if c.isdigit() or c == ".")
    gil = gil_state()
    logpath = os.path.join(PLURIBUS, "tmp", f"ft_refcount_bench_{tag}.log")
    fh = open(logpath, "w")

    def log(*a):
        msg = " ".join(str(x) for x in a)
        print(msg, flush=True)
        fh.write(msg + "\n")
        fh.flush()

    log(f"# python {sys.version}")
    log(f"# gil_enabled={gil} cpu_count={os.cpu_count()} R={R} bit={BIT}")

    pb = native_bitstream.parse_file(BIT)
    log(f"# cram frames={pb.frames_read}/{pb.num_frames} "
        f"crc_verified={pb.crc_verified} bits_per_frame={pb.bits_per_frame}")
    tilegrid = ntd.load_tilegrid(DEVICE, DB)
    tiles = list(tilegrid.items())

    # Warm the type cache; build a prepared (tt, foff, boff) list of SHARED refs.
    for _, m in tiles:
        ntd.get_tile_type(m["type"], DB)
    prepared_shared = [(ntd.get_tile_type(m["type"], DB),
                        m["start_frame"], m["start_bit"]) for _, m in tiles]
    cram_shared = pb.cram

    # Correctness fingerprint: canonical decode of the whole chip (serial).
    cfg = ntd.decode_chip(cram_shared, tilegrid, DB, workers=1)
    can = ntd.canonical(cfg)
    narcs = sum(len(t["arcs"]) for t in can.values())
    nwords = sum(len(t["words"]) for t in can.values())
    nenums = sum(len(t["enums"]) for t in can.values())
    fp = f"tiles={len(can)} arcs={narcs} words={nwords} enums={nenums}"
    log(f"# FINGERPRINT {fp}")

    def decode_n_shared(rep):
        for _ in range(rep):
            for tt, foff, boff in prepared_shared:
                ntd.decode_tile(tt, cram_shared, foff, boff)

    def decode_n_private(rep):
        cram_p = [bytearray(row) for row in cram_shared]
        prep_p = [(ntd.parse_bits_db(os.path.join(
                       DB, "MachXO2", "tiledata", m["type"], "bits.db")),
                   m["start_frame"], m["start_bit"]) for _, m in tiles]
        for _ in range(rep):
            for tt, foff, boff in prep_p:
                ntd.decode_tile(tt, cram_p, foff, boff)

    # Serial baseline (shared refs, single thread) -- the reference time.
    decode_n_shared(4)  # warm
    best = None
    for _ in range(3):
        t0 = time.perf_counter()
        decode_n_shared(R)
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    t_serial = best
    log(f"RESULT case=serial threads=1 R={R} ms={t_serial*1000:.1f} "
        f"speedup=1.00 ms_per_decode={t_serial/R*1000:.2f}")

    def run_case(label, fn):
        for T in THREAD_COUNTS:
            if T > (os.cpu_count() or 4):
                break
            per = max(1, R // T)
            # best of 2 runs to reduce noise
            best_dt = None
            for _ in range(2):
                threads = [threading.Thread(target=fn, args=(per,))
                           for _ in range(T)]
                t0 = time.perf_counter()
                for th in threads:
                    th.start()
                for th in threads:
                    th.join()
                dt = time.perf_counter() - t0
                best_dt = dt if best_dt is None else min(best_dt, dt)
            # work done = T*per decodes; normalise speedup to serial per-decode
            work = T * per
            eff_serial = t_serial * (work / R)
            sp = eff_serial / best_dt
            log(f"RESULT case={label} threads={T} per={per} work={work} "
                f"ms={best_dt*1000:.1f} speedup={sp:.2f}")

    log("# --- SHARED data (intra-bitstream; the contention case) ---")
    run_case("shared", decode_n_shared)
    log("# --- PRIVATE data (bitstream-level control; should scale) ---")
    run_case("private", decode_n_private)

    log(f"# DONE gil_enabled={gil} fingerprint: {fp}")
    fh.close()


if __name__ == "__main__":
    main()
