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
- `ecp5_corpus_test.py`: threads (default) sharing one graph per device; `--mode procs` = old per-process mode (A/B).
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
