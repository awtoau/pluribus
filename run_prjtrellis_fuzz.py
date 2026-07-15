#!/usr/bin/env python3
"""run_prjtrellis_fuzz.py — run the prjtrellis machxo2 fuzzer suite via Diamond 3.14.

Runs every fuzzer that has a fuzzer.py, from its own directory, exactly as the
prjtrellis project does. Diamond's NCL flow is invoked by each fuzzer.py.

Usage:
    python3 run_prjtrellis_fuzz.py              # all fuzzers
    python3 run_prjtrellis_fuzz.py "051-*"      # pattern filter
    python3 run_prjtrellis_fuzz.py --jobs N     # outer parallel fuzzers (default: auto)

Parallelism:
    --jobs controls how many fuzzers run concurrently (outer loop).
    TRELLIS_JOBS controls Diamond threads per fuzzer (inner loop).
    Both are auto-set to saturate available cores: jobs * trellis_jobs ≈ cpu_count.

Instrumentation:
    Every 100ms a sampler thread records per-process CPU% and thread lock-wait time
    into tmp/prjtrellis_run/perf.db (SQLite). Two tables:
      cpu_samples(ts REAL, pid INT, name TEXT, cpu_pct REAL, num_threads INT)
      lock_waits(ts REAL, pid INT, name TEXT, iowait_pct REAL, system_pct REAL)
    Query after a run:
      sqlite3 tmp/prjtrellis_run/perf.db
        "SELECT name, AVG(cpu_pct), MAX(cpu_pct) FROM cpu_samples GROUP BY name"

Output:
    tmp/prjtrellis_run/<fuzzer_name>.log  — per-fuzzer stdout+stderr
    tmp/prjtrellis_run/summary.txt        — one line per fuzzer + totals
    tmp/prjtrellis_run/perf.db            — 100ms CPU + lock-wait samples
"""
from __future__ import annotations
import argparse
import fnmatch
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pg8000.native

_ROOT     = Path(__file__).parent
_PRJT     = Path(os.environ.get("TRELLIS_ROOT",
                 "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis"))
_FUZZ_DIR = _PRJT / "fuzzers/machxo2"
_LOG_DIR  = _ROOT / "tmp/prjtrellis_run"

_NCPUS = os.cpu_count() or 4
_PG_DB   = os.environ.get("PGDATABASE",    "fpga_re")
_PG_USER = os.environ.get("PGUSER",        os.environ.get("USER", "dan"))
_PG_SOCK = os.environ.get("PGUNIXSOCKET",  "/run/postgresql/.s.PGSQL.5432")

# Names of processes we care about
_WATCH = {"bitgen", "diamond", "fuzzer.py", "run_prjtrellis"}


def _make_env(trellis_jobs: int) -> dict:
    return {
        **os.environ,
        "DIAMONDDIR":      "/home/dan/lscc/diamond/3.14",
        "DIAMONDVER":      "3.14",
        "LM_LICENSE_FILE": "/home/dan/lscc/diamond/3.14/license/license.dat",
        "TRELLIS_JOBS":    str(trellis_jobs),
        "PYTHONPATH": ":".join([
            str(_PRJT / "libtrellis/build"),
            str(_PRJT / "util/fuzz"),
            str(_PRJT / "util/common"),
            str(_PRJT / "util/common/nets"),
            str(_PRJT / "util"),
        ]),
        "LD_LIBRARY_PATH": str(_PRJT / "libtrellis/build"),
    }


# ── instrumentation ──────────────────────────────────────────────────────────

def _pg_connect() -> pg8000.native.Connection:
    return pg8000.native.Connection(
        database=_PG_DB, user=_PG_USER, unix_sock=_PG_SOCK)


def _init_perf_tables(con: pg8000.native.Connection) -> None:
    con.run("""
        CREATE TABLE IF NOT EXISTS fuzz_cpu_samples (
            ts          DOUBLE PRECISION NOT NULL,
            pid         INTEGER NOT NULL,
            name        TEXT NOT NULL,
            cpu_pct     REAL NOT NULL,
            num_threads INTEGER NOT NULL
        )""")
    con.run("""
        CREATE TABLE IF NOT EXISTS fuzz_lock_waits (
            ts          DOUBLE PRECISION NOT NULL,
            pid         INTEGER NOT NULL,
            name        TEXT NOT NULL,
            iowait_s    REAL NOT NULL,
            system_s    REAL NOT NULL
        )""")


def _sampler(stop: threading.Event) -> None:
    """Sample every 100 ms; write CPU% and system/iowait time to postgres."""
    con = _pg_connect()
    _init_perf_tables(con)

    interval    = 0.1
    flush_every = 20      # flush every 2 s
    tick        = 0
    batch_cpu: list[tuple] = []
    batch_lw:  list[tuple] = []

    while not stop.is_set():
        ts = time.time()
        try:
            for proc in psutil.process_iter(
                    ["pid", "name", "cpu_percent", "num_threads"]):
                info = proc.info
                pname = info["name"] or ""
                if not any(w in pname for w in _WATCH):
                    continue
                pid = info["pid"]
                cpu = info["cpu_percent"] or 0.0
                nth = info["num_threads"] or 0
                batch_cpu.append((ts, pid, pname, cpu, nth))
                try:
                    ct = proc.cpu_times()
                    batch_lw.append((ts, pid, pname,
                                     getattr(ct, "iowait", 0.0),
                                     ct.system))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        tick += 1
        if tick >= flush_every and batch_cpu:
            tick = 0
            for r in batch_cpu:
                con.run("INSERT INTO fuzz_cpu_samples VALUES (:ts,:pid,:name,:cpu,:nth)",
                        ts=r[0], pid=r[1], name=r[2], cpu=r[3], nth=r[4])
            for r in batch_lw:
                con.run("INSERT INTO fuzz_lock_waits VALUES (:ts,:pid,:name,:io,:sys)",
                        ts=r[0], pid=r[1], name=r[2], io=r[3], sys=r[4])
            batch_cpu.clear()
            batch_lw.clear()

        stop.wait(interval)

    # final flush
    for r in batch_cpu:
        con.run("INSERT INTO fuzz_cpu_samples VALUES (:ts,:pid,:name,:cpu,:nth)",
                ts=r[0], pid=r[1], name=r[2], cpu=r[3], nth=r[4])
    for r in batch_lw:
        con.run("INSERT INTO fuzz_lock_waits VALUES (:ts,:pid,:name,:io,:sys)",
                ts=r[0], pid=r[1], name=r[2], io=r[3], sys=r[4])


# ── fuzzer runner ─────────────────────────────────────────────────────────────

def _run_one(fuzzer_dir: Path, env: dict, summary_lock: threading.Lock,
             summary_file: Path, passed: list, failed: list,
             print_lock: threading.Lock) -> None:
    name = fuzzer_dir.name
    log  = _LOG_DIR / f"{name}.log"
    t0   = time.monotonic()

    with print_lock:
        print(f"  [START] {name}", flush=True)

    with open(log, "w") as lf:
        rc = subprocess.run(
            [sys.executable, "fuzzer.py"],
            cwd=str(fuzzer_dir),
            env=env,
            stdout=lf,
            stderr=lf,
        ).returncode

    elapsed = time.monotonic() - t0
    tag = "PASS" if rc == 0 else "FAIL"

    with print_lock:
        print(f"  {tag}  {name}  ({elapsed:.0f}s)", flush=True)
        if rc != 0:
            tail = log.read_text().splitlines()[-5:]
            for line in tail:
                print(f"        {line}", flush=True)

    with summary_lock:
        with open(summary_file, "a") as sf:
            sf.write(f"{tag}  {name}  ({elapsed:.0f}s)\n")
        if rc == 0:
            passed.append(name)
        else:
            failed.append(name)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", nargs="?", default="*",
                    help="Glob filter on fuzzer dir names")
    ap.add_argument("--jobs", type=int, default=0,
                    help="Outer parallel fuzzers (default: auto-balance with cpu count)")
    args = ap.parse_args()

    trellis_jobs = 2
    outer_jobs   = args.jobs if args.jobs > 0 else max(1, (_NCPUS - 2) // trellis_jobs)

    print(f"  cpus={_NCPUS}  outer_jobs={outer_jobs}  trellis_jobs={trellis_jobs}"
          f"  (max Diamond processes ≈ {outer_jobs * trellis_jobs})", flush=True)

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    summary_file = _LOG_DIR / "summary.txt"
    summary_file.write_text("")

    env = _make_env(trellis_jobs)

    fuzz_dirs = sorted(
        d for d in _FUZZ_DIR.iterdir()
        if d.is_dir()
        and fnmatch.fnmatch(d.name, args.pattern)
        and (d / "fuzzer.py").exists()
    )
    skipped_count = sum(
        1 for d in _FUZZ_DIR.iterdir()
        if not (d.is_dir() and fnmatch.fnmatch(d.name, args.pattern)
                and (d / "fuzzer.py").exists())
    )

    # start instrumentation sampler
    stop_sampler = threading.Event()
    sampler_thread = threading.Thread(
        target=_sampler, args=(stop_sampler,), daemon=True)
    sampler_thread.start()
    print(f"  perf logging → postgres:{_PG_DB} (fuzz_cpu_samples, fuzz_lock_waits)", flush=True)

    passed: list[str] = []
    failed: list[str] = []
    summary_lock = threading.Lock()
    print_lock   = threading.Lock()

    queue = list(fuzz_dirs)
    queue_lock = threading.Lock()

    def worker():
        while True:
            with queue_lock:
                if not queue:
                    return
                fd = queue.pop(0)
            _run_one(fd, env, summary_lock, summary_file, passed, failed, print_lock)

    t_start = time.monotonic()
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(outer_jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stop_sampler.set()
    sampler_thread.join()

    elapsed_total = time.monotonic() - t_start

    # print perf summary from postgres
    try:
        pcon = _pg_connect()
        rows = pcon.run("""
            SELECT name,
                   ROUND(AVG(cpu_pct)::numeric, 1) avg_cpu,
                   ROUND(MAX(cpu_pct)::numeric, 1) max_cpu,
                   COUNT(*) samples
            FROM fuzz_cpu_samples
            GROUP BY name
            ORDER BY avg_cpu DESC
        """)
        print(f"\n  --- CPU profile (postgres:{_PG_DB}.fuzz_cpu_samples) ---", flush=True)
        for name, avg, mx, n in rows:
            print(f"    {name:30s}  avg={avg:5.1f}%  max={mx:5.1f}%  n={n}", flush=True)
        lw_rows = pcon.run("""
            SELECT name,
                   ROUND(AVG(system_s)::numeric, 3) avg_sys,
                   ROUND(AVG(iowait_s)::numeric, 3) avg_io
            FROM fuzz_lock_waits
            GROUP BY name
            ORDER BY avg_sys DESC
        """)
        print(f"\n  --- lock/system time ---", flush=True)
        for name, sys_t, io_t in lw_rows:
            print(f"    {name:30s}  avg_sys={sys_t}s  avg_iowait={io_t}s", flush=True)
    except Exception as e:
        print(f"  (perf summary failed: {e})", flush=True)

    with open(summary_file, "a") as sf:
        sf.write(f"\n=== Summary ({elapsed_total:.0f}s total) ===\n")
        sf.write(f"  Passed:  {len(passed)}\n")
        sf.write(f"  Failed:  {len(failed)}\n")
        sf.write(f"  Skipped: {skipped_count}\n")

    print(f"\n=== prjtrellis fuzz complete ({elapsed_total:.0f}s) ===", flush=True)
    print(f"  Passed:  {len(passed)}", flush=True)
    print(f"  Failed:  {len(failed)}", flush=True)
    print(f"  Skipped: {skipped_count}", flush=True)
    if failed:
        print(f"  Failures:", flush=True)
        for f in failed:
            print(f"    {f}", flush=True)
    print(f"  Summary: {summary_file}", flush=True)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
