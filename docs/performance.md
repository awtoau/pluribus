# Performance and memory audit

Conditions: 2026-10-26, 30-core / 62 GB box, load average 12-15 from other agents, python3.15t.
Timings are wall time under that load; re-measure before relying on them.

## Changes (accuracy impact: none, signature/outputs verified)

| change | before | after | evidence |
|---|---|---|---|
| `NativeRoutingGraph` built once per (device, db, family) per process, freed by weakref | 1 graph per lifter / worker thread | 1 per process | `native_trellis/pytrellis_compat.py`; graph RSS 1.9 GB (25F), 3.3 GB (45F), ~6 GB (85F, from 7.5 GB per-process peak in `rss_sedga85`) saved per extra worker |
| `globalise_net` name parse memoised (both families) | 9.1 M calls re-parse each name | parse once per name | `native_trellis/globalise.py` |
| graph build threaded on free-threaded python (private caches, private string copies; `PLURIBUS_RGRAPH_THREADS`, default min(cpu, 8)) | LFE5U-12F 18.3 s, LFE5U-45F 18.4 s, LCMXO3-9400 5.2 s | 7.4 s, 6.7 s, 2.4 s | `scripts/rgraph_signature.py`: SHA-256 of wires/arcs/bels identical on 12F, 25F, 45F, LCMXO2-1200, LCMXO2-7000, LCMXO3-9400 |
| Quartus flow skipped when input hash unchanged (`quartus.key`; `--rebuild`, `--adopt-keys`) | every run rebuilds all designs, 12.8 s mean per design (486 builds, `cyclonev_corpus_build.log`) | unchanged design: 0 s Quartus (decomp + lift still rerun) | `scripts/cyclonev_corpus_build.py` |
| `cyclonev_corpus_build.py --jobs` default derived from RAM | 1 | up to 6 | quartus_fit 1.06 GB, quartus_map 0.53 GB RSS (single design) |
| `cyclonev_lifted_sim_check.py` JOBS derived from RAM | 4 | 8 | per-design 0.7-0.8 s, load.py 66 MB / verilog.py 62 MB RSS |
| MachXO2 compare: `garcs` built once per process | 1 copy per worker thread | 1 | `scripts/machxo2_oracle_compare.py` |

## Single knob for RAM

- `heavy_guard.JOB_GB`: measured peak GB per job type (this table is the only copy).
- `heavy_guard.workers_for(job, cap)`: floor(BATCH_MAX_GB x 0.8 / JOB_GB[job]), clamped to [1, cap]; unmeasured job = KeyError.
- RAM upgrade: set `PLURIBUS_BATCH_MAX_GB` (scope cap, default 28) and `PLURIBUS_MIN_AVAILABLE_GB` (start gate, default 12); worker defaults follow.

## Measured, not changed

- `quartus_fit --parallel`: c_adder_sv_16, fit 7.1 s default / 8.0 s `=1` / 7.2 s `=8` / 7.3 s default again. No effect at corpus size; left at default.
- iverilog + vvp: 0.05 + 0.12 s per design; the sim gate is dominated by two python3.15t child startups (0.25-0.37 s each). Not worth caching.
- ECP5 compare per target (25F, 2.2 GB RSS, 54 s wall incl. graph build): graph build ~11 s, native bitstream decode ~4-9 s (`decode_tile`/`_match`, already threaded in `decode_chip`), rest small.

## Proposed `--fast` (not implemented)

- None worth the accuracy cost found: the large costs (graph build, rebuilds) were removed without touching coverage.
