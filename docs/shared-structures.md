# Shared per-device structures (free-threaded Python) - #148

Rule: data that depends only on the device is built once per process and read by all threads; per-design state is private.
Measured 2026-10-29, python3.15t, 85F designs, PSS peak, box shared with other agents (walls +-20%). Raw: `scripts/ecp5_share_bench.py`, `tmp/share-bench/*.json`.

## Classification

| structure | where | size (85F) | depends on | mutated after build | class |
|---|---|---|---|---|---|
| wire-name sets, SLICE/PIO bels | `native_trellis/rgraph.py` `NativeRoutingGraph.wires/bels` | ~0.9 GB, 3.8 M wires, 3.9 s build | device | no | immutable, shared (`pytrellis_compat._shared_for`) |
| arcs (28 M Arc tuples) | `NativeRoutingGraph.arcs` | ~5 GB, ~9 s | device | no | no lifter reads it; not built unless `keep_arcs=True` (parity tools) |
| compat tiles/wires/bels | `pytrellis_compat.RoutingGraph.tiles` | was ~0.4 GB | device | no | now built on access, nothing stored |
| tile-type bits.db parse | `tiledb.load_tiletype` (`lru_cache`) | small | family+tiletype | filled lazily, values never mutated | immutable once filled; thread-safe |
| `Globaliser._name_cache` | `globalise.py` | ~MB | device | lazy memo, idempotent immutable tuples | benign race (duplicate work only); effectively pre-filled by the graph build |
| slice/pio bel templates | `rgraph._slice_templates` (`lru_cache`) | tiny | none | no | immutable |
| `_PLC_ENUM_DEFAULTS` | `ecp5_lift.py`, `machxo2_lift.py` | tiny | dbroot | lazy, idempotent | benign race |
| clock geometry JSON (`_ckg`) | `ECP5Lift._clock_geom` | small | device | lazy, per lift | read-only; candidate to share |
| `_wn_index` | `ECP5Lift` | grew per lift | device | lazy | removed on native backend (id == name) |
| `_bel_cache`, `_prefer_mux_nodes`, DSU, Design | lifters | per design | design | yes | per-design, cannot share |
| decode tables / tilegrid (`native_config`, `native_bitstream`) | scripts/ | not audited | device | ? | not audited (other owner) |

## Concurrency today
- `ecp5_corpus_test.py`: threads sharing one graph per device (the process mode was removed, #149).
- Graph cache: strong per-process (`PLURIBUS_RGRAPH_CACHE=weak` restores the old free-when-idle behaviour, which rebuilt the graph for serial lifts).
- Not audited: Gowin, Cyclone IV/V lifters, reach* (SQL-bound), MachXO2 sweeps.

## Results (85F, one lift per thread)

| concurrent lifts | before (HEAD) | after |
|---|---|---|
| 1 | 5.98 GB, 24 s | 0.85 GB, 11.7 s |
| 4 | 7.09 GB, 35 s | 2.0 GB, 21 s |
| 8 | not run (lease) | 2.15 GB, 25 s |

- Old process mode, extrapolated from the 1-lift row: 8 x ~6 GB, far above the 28 GB lease budget; not run.
- The 30 GB figure does not reproduce in threads mode at HEAD (4 lifts = 7.1 GB, graph already shared); it was the per-process mode.
- Outputs identical on 13 designs (12F/25F/45F/85F): config, LUTs, FFs, nets, arcs, metrics, Verilog digests.
- Thread safety: `tests/test_native_trellis_threads.py` (8 threads vs 1, concurrent `Chip()` builds once).

## Next candidates
- Share `_clock_geom` per device; audit `native_config` decode tables.
- Same audit for Gowin / Cyclone IV/V lifters.

## Round 2 (#149): RAM by pipeline, measured 2026-10-29

Tool: `scripts/mem_report.py STAGE|--script FILE [--tracemalloc]` (peak RSS split anonymous vs file-backed, per-phase marks, top allocations; leases first).
Anonymous = heap + numpy = real pressure. File-backed = `np.load(mmap_mode='r')` pages: shared page cache, reclaimable, one copy for all processes.
tracemalloc inflates Python-object-heavy runs 3x (reach2: 7 GB vs 1.5 GB): lease declared peaks come from the untraced run.

| pipeline (real input) | RSS before | RSS after | anon before -> after | wall before -> after | fix |
|---|---|---|---|---|---|
| ECP5 85F lift, 1 | 5.98 GB | 0.68 GB | | 24 -> 10.9 s | arcs dropped, tiles/bels built on access (#148, #149) |
| ECP5 85F lifts, 8 threads | not run (extrap. 8 x 6 GB by process) | 2.05 GB | | 25 s | same |
| Dec.active (asm_active) | 2.10 GB | 1.11 GB | 1.51 -> 0.40 | 1.1 -> 0.7 s | all tables mmap, names lazy, flat index cached on disk, int32 temporaries |
| ddb_trace score x3 | 3.26 GB | 2.51 GB | 2.52 -> 1.70 | 6.9 -> 5.9 s | same (Dec) |
| bit_inventory | 2.63 GB | 2.34 GB | 1.03 | ~9 s | Dec; fails at the end on missing evidence rows (not memory) |
| reach2 fnirsi | 1.48 GB | 0.61 GB | | 17.6 -> 14.3 s | stream rows instead of fetchall (ff_cones sha256 identical) |
| reach fnirsi / ddb_fanout / lift_ecp5 25F / corpus_register / cram decode / MachXO2 lift | 0.29 / 0.87 / 0.34 / 0.11 / 0.17 / 0.05 GB | unchanged | | | below 1 GB, not worth touching |

Acceptance: `Dec.active` gids/records/blocks sha256 identical on 6 designs; `rgraph_signature` (wires, bels, arcs) identical on LFE5U-25F and LCMXO2-1200; 13-design lift digest identical; ff_cones identical.

Still large:
- Tracer anonymous 1.7 GB: per-die int64 tables of 17 M groups/units (`group_edges` k/dest, `Pairs`, `udest`, 130 MB each), `li_of` dict (66 MB), route-learner tuples (100 MB). Next: downcast to int32 and persist as mmap files.
- File-backed 1.1 GB of Dec tables: one copy in page cache for any number of processes.
- 85F lift 0.68 GB: 3.8 M wire-name set entries (no duplicate strings: interning measured 0 gain).
- Not audited: `native_config` decode tables, Gowin / Cyclone V lifters (tests only, small).
- Lease telemetry under-reports subprocess jobs (profile_stages leases from the parent): numbers above come from wait4 rusage / `/proc` sampling.

Concurrent jobs in the 28 GB lease budget (budget x 0.8 = 22.4 GB planned, `heavy_guard.workers_for`):

| job | per job before | before | per job after | after |
|---|---|---|---|---|
| ECP5 85F lifts, processes | 7.5 GB | 2 | 1.0 GB | 22 |
| ECP5 85F lifts, threads of one process | 0.8 + 0.2 per extra | n/a | | 100+ (CPU-bound, use <= 8) |
| Dec.active | 2.5 GB | 8 | 1.2 GB | 18 |
| ddb_trace score | 3.7 GB | 6 | 2.6 GB | 8 |
| bit_inventory | 3.0 GB | 7 | 2.6 GB | 8 |
| reach2 fnirsi | 1.5 GB | 14 | 0.7 GB | 32 |

## Round 3 (#149): process pools removed, A/B on real inputs, 2026-10-29

Every converted script now runs a `ThreadPoolExecutor` in one process; external tools (yosys, ecpunpack) and the `load.py` stage CLI stay subprocesses.
Peak = PSS summed over the process tree (`scripts/ab_measure.py`), box shared with other agents (walls +-20%).

| script (input, workers) | outputs | wall procs -> threads | PSS procs -> threads |
|---|---|---|---|
| ecp5_corpus_test (11 designs 12F..85F, 4) | results JSON identical | 34.6 -> 34.6 s (59 s with per-job leases: 3 s lease ramp x 11 jobs) | 2.88 -> 2.06 GB |
| lifter_equiv_corpus (1000 fuzz targets, 8) | identical (61 equivalent, 929 decoded, 9 no_bit); only yosys timing/MEM tail differs | 29.5 -> 38.7 s | 0.60 -> 0.13 GB |
| unknown_bits_census (600 bitstreams, 8) | JSON identical | 15.2 -> 18.8 s | 0.41 -> 0.08 GB |
| native_corpus_parity (400 fuzz bitstreams, 8) | report identical (318 ok, 82 DIVERGED, 13,882 tiles) | 7.5 -> 9.7 s | 0.62 -> 0.10 GB |
| validate_fuzz (40 targets, 4) | 38/40 validate.txt identical to serial; 2 SQLite "database is locked" (also under procs) | 4.6 -> 4.7 s | 0.41 -> 0.35 GB |
| ecp5_share_bench | procs variant removed | | |

- Short jobs (< 1 s each) take one lease for the pool (workers x `JOB_GB`); a per-job lease costs the 3 s `LEASE_RAMP_S` each.
- Threads are 0-30% slower in wall on the small-job sweeps (yosys spawn from a multi-threaded process, shared-object refcount contention) for 4-8x less memory.
- Per-thread state: `lifter_equiv_corpus` keeps one `MachXO2Lift` per worker thread (`threading.local`); pin map loaded once under a lock.
- `native_corpus_parity`: fd 1 is pointed at /dev/null once (pytrellis C++ output); the log writes to a dup of the original stdout.
- Not converted: `cpu_sanity_check.py` (one pinned subprocess per CPU to test each core; a thread cannot isolate a core's fault from the shared process) and stage-CLI subprocess pools (`ecp5_verify_all.py`, `*_verify_all.py`, `machxo2_oracle_*`): they spawn one python CLI per job from threads; in-process mains are a separate change.
- Guard: `tests/test_threads_only.py` fails on `multiprocessing` / `ProcessPoolExecutor` / `os.fork` in tracked code.
