# Memory budget (RAM is the limit, not CPU)

- Box: 62 GB RAM, 30 cores. OOM kills and swap thrash (zram + swapfile) are what slow or take down the box, not CPU load.
- Every heavy job (Quartus chains, Dec.active/tracer/inventory runs, ECP5 lifts, regen scripts, profiling) holds a lease:
  `with heavy_guard.lease(GB, name, log): ...` (scripts/heavy_guard.py). `build_pool.map_adaptive` does it per job.
- Lease = shared GB semaphore across all processes (ledger beside the heavy lock in the git common dir).
  Admits while sum(leases) + GB <= PLURIBUS_LEASE_BUDGET_GB (default = PLURIBUS_BATCH_MAX_GB = 28), AVAILABLE RAM - GB
  >= PLURIBUS_MIN_AVAILABLE_GB (12), no lease younger than 3 s (peak ramp). Jobs run side by side; no speed loss until the budget is full.
- `heavy_lock` stays for whole-batch exclusivity and scope isolation (MemoryMax=28G, no swap: the batch is the kill target, not the IDE).
- Declare peaks from measurements: `heavy_guard.JOB_GB` (quartus chain 1.5, Dec.active 2.5, tracer 3.7, inventory 3.0, ECP5 85F lift 7.5).
  Unmeasured job: measure (profile_stages.py), add it, then lease.
- Share read-only per-device data across THREADS (python3.15t), not processes: processes duplicate the multi-GB tables.
- Status: `python3.15t -c "import heavy_guard,json;print(json.dumps(heavy_guard.lease_ledger(),indent=1))"` from scripts/.
