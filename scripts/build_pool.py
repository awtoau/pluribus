"""Adaptive worker pool for Quartus build sweeps: fill the box, never swap or fill the disk.

  import build_pool
  results = build_pool.map_adaptive(fn, items, per_job_gb=2.0)   # results in item order

Admission (checked before each job starts, polled every POLL_S):
  - workers in flight < max_workers (default cores - 4, headroom for the desktop and other agents)
  - a heavy_guard.lease(per_job_gb): the box-wide GB budget shared with every other sweep/agent
    (a Quartus chain peaks ~1.3 GB; 2.0 leaves margin) and the AVAILABLE-RAM floor
  - disk free >= disk_floor_gb (ENOSPC hit twice on 2026-10-28)
  - STAGGER_S since the last start, so MemAvailable reflects the previous job before the next check
If nothing is in flight and memory is still short for ADMIT_ANYWAY_S, one job is admitted anyway
(someone else holds the RAM; waiting forever is a hang) and the event is logged.
Threads, not processes: jobs are subprocess waits plus numpy/bit work, safe under python3.15t.
"""
import logging
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard  # noqa: E402

log = logging.getLogger("build_pool")

POLL_S = 1.0            # admission re-check; MemAvailable moves on a ~second scale
STAGGER_S = 2.0         # a started chain reaches its map-step allocation in ~2 s (map takes ~9 s)
ADMIT_ANYWAY_S = 60.0   # idle pool + short RAM this long = foreign RAM hog, run one job anyway


def mem_available_gb():
    for ln in Path("/proc/meminfo").read_text().splitlines():
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1]) / 2**20
    raise RuntimeError("MemAvailable missing from /proc/meminfo")


def map_adaptive(fn, items, per_job_gb=2.0, reserve_gb=10.0, max_workers=None, disk_floor_gb=10.0):
    items = list(items)
    max_workers = max_workers or max(1, (os.cpu_count() or 8) - 4)
    cv = threading.Condition()
    state = {"inflight": 0, "last_start": 0.0, "peak": 0}
    done = [0]
    t0 = time.monotonic()

    def admit():
        waited_since = time.monotonic()
        while True:
            with cv:
                now = time.monotonic()
                free_disk = shutil.disk_usage(REPO).free / 2**30
                ok_mem = True  # RAM is gated by the shared lease in run()
                ok_slot = state["inflight"] < max_workers
                ok_time = now - state["last_start"] >= STAGGER_S
                if free_disk < disk_floor_gb:
                    log.error("disk free %.1f GB < floor %.0f: not admitting new jobs", free_disk, disk_floor_gb)
                elif ok_slot and ok_time and (ok_mem or (state["inflight"] == 0 and now - waited_since >= ADMIT_ANYWAY_S)):
                    if not ok_mem:
                        log.error("admitting one job on low RAM (%.1f GB avail, idle pool %.0fs)",
                                  mem_available_gb(), now - waited_since)
                    state["inflight"] += 1
                    state["peak"] = max(state["peak"], state["inflight"])
                    state["last_start"] = now
                    return
            time.sleep(POLL_S)

    def run(item):
        admit()
        try:
            with heavy_guard.lease(per_job_gb, "build_pool", log):
                return fn(item)
        finally:
            with cv:
                state["inflight"] -= 1
                done[0] += 1
                if done[0] % 20 == 0:
                    log.info("pool: %d/%d done, %d in flight, avail %.1f GB, %.0fs",
                             done[0], len(items), state["inflight"], mem_available_gb(), time.monotonic() - t0)

    with ThreadPoolExecutor(max_workers) as ex:
        out = list(ex.map(run, items))
    log.info("pool: %d jobs in %.0fs, peak %d in flight (cap %d)", len(items), time.monotonic() - t0,
             state["peak"], max_workers)
    return out
