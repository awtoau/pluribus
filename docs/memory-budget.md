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
- **Threads everywhere (Dan, 2026-10-29).** Parallelism in pluribus code is threads under free-threaded python3.15t, not multiprocessing: one copy of per-device data, one lease, no per-process duplicates. Processes only for external tools (Quartus, Diamond, yosys). Efficiency wins over stability: a bug in one thread can take the whole run down, accepted by design (stall timeouts and per-job leases still apply). No process-isolation mode is kept. Process pools removed (#149); `tests/test_threads_only.py` fails on any new one.
- Measure: every lease writes one line to tmp/logs/lease_telemetry.jsonl (declared GB, wait, hold, observed peak RSS growth, concurrency). `python3.15t scripts/heavy_guard.py report` compares declared vs observed per name; correct JOB_GB from it. Waiting costs no CPU (event waits); a job blocked >60 s sheds cached memory (gc + malloc_trim). Acquire the lease BEFORE loading big data.
