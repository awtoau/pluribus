#!/usr/bin/env python3
"""run_machxo2_fuzz.py — run the MachXO2 comprehensive routing fuzzer.

Wraps fuzz_machxo2_full.py for background execution.
Resumable: already-completed runs are skipped automatically by the DB.
Safe to kill and restart at any time.

Usage:
    python3 run_machxo2_fuzz.py           # run all devices
    python3 run_machxo2_fuzz.py --kill    # kill any running instance
    python3 run_machxo2_fuzz.py --status  # print DB summary and exit

Log:  tmp/fuzz_full.log
DB:   fpga_re (Postgres) — fuzz_runs / fuzz_wires tables
"""
from __future__ import annotations
import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

_TOOLS  = Path(__file__).resolve().parent   # this file lives in <repo>/tools/
_ROOT   = _TOOLS.parent                       # repo root
_LOG    = _ROOT / "tmp" / "fuzz_full.log"
_FUZZER = _TOOLS / "fuzz_machxo2_full.py"     # sibling in tools/
_PRJT   = Path(os.environ.get("TRELLIS_ROOT", "tmp/prjtrellis"))


def status():
    import pg8000.dbapi as pg8000  # pg8000 only (psycopg2 removed from this system)
    con = pg8000.connect(
        database=os.environ.get("PGDATABASE", "fpga_re"),
        user=os.environ.get("PGUSER") or os.environ.get("USER"),
        unix_sock=os.environ.get("PGUNIXSOCKET", "/run/postgresql/.s.PGSQL.5432"),
    )
    cur = con.cursor()
    cur.execute(
        "SELECT device, status, COUNT(*) as n FROM fuzz_runs "
        "GROUP BY device, status ORDER BY device, status"
    )
    rows = cur.fetchall()
    total = sum(r[2] for r in rows)
    print(f"DB: fpga_re  ({total} total runs)")
    print(f"{'device':<22} {'status':<20} {'count':>6}")
    print("-" * 52)
    for device, st, n in rows:
        print(f"  {device:<20} {st:<20} {n:>6}")
    cur.execute(
        "SELECT COUNT(*) FROM fuzz_runs WHERE status NOT IN ('ok','pnr_fail')"
    )
    missing = cur.fetchone()[0]
    if missing:
        print(f"\nIn-progress/error: {missing} runs")
    con.close()


def kill():
    result = subprocess.run(
        ["pgrep", "-f", Path(__file__).name],
        capture_output=True, text=True
    )
    pids = [int(p) for p in result.stdout.split() if p and int(p) != os.getpid()]
    if not pids:
        print("no running instances found")
        sys.exit(0)
    for pid in pids:
        os.kill(pid, signal.SIGTERM)
        print(f"killed PID {pid}")
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kill",   action="store_true", help="Kill running instances and exit")
    ap.add_argument("--status", action="store_true", help="Print DB summary and exit")
    args = ap.parse_args()

    if args.kill:
        kill()

    if args.status:
        status()
        return

    # Check for existing instance
    result = subprocess.run(
        ["pgrep", "-f", Path(__file__).name],
        capture_output=True, text=True
    )
    existing = [int(p) for p in result.stdout.split() if p and int(p) != os.getpid()]
    if existing:
        print(f"ERROR: already running as PID(s) {existing}")
        print("Use --kill to stop it, or --status to check progress.")
        sys.exit(1)

    print(f"Starting fuzzer. Log: {_LOG}", flush=True)
    print("DB:  fpga_re (Postgres) — fuzz_runs / fuzz_wires", flush=True)
    print("Covers: all 6 LCMXO2 devices × all packages × pad/lut/carry/dpram/ebr/pll/iologic/efb/longline", flush=True)
    print("Resumable — safe to kill and restart at any time.", flush=True)

    _LOG.parent.mkdir(parents=True, exist_ok=True)

    with open(_LOG, "a") as log_fh:
        log_fh.write(f"\n=== fuzz_machxo2_full.py started ===\n")
        log_fh.flush()
        proc = subprocess.Popen(
            [sys.executable, str(_FUZZER), "--all-devices", "--jobs", "24"],
            stdout=log_fh,
            stderr=log_fh,
            env={**os.environ,
                 "TRELLIS_BUILD":  str(_PRJT / "libtrellis/build"),
                 "TRELLIS_DBROOT": str(_PRJT / "database")},
        )
        print(f"Fuzzer PID: {proc.pid}", flush=True)
        print(f"Tail the log: tail -f {_LOG}", flush=True)
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            print("\nInterrupted — fuzzer stopped. DB is safe, restart to resume.")
            sys.exit(0)

    rc = proc.returncode
    if rc == 0:
        print("Fuzzer completed successfully.")
        status()
    else:
        print(f"Fuzzer exited with code {rc} — check {_LOG}")
        sys.exit(rc)


if __name__ == "__main__":
    main()
