# Rust candidates — measured (#144)

Verdict (2026-10-29, commit of this file): **nothing in pluribus clearly earns a Rust rewrite today.**
No stage meets the bar (>= 5-10x on a stage that dominates a pipeline's wall, or a memory cut that
unlocks a run). Every hotspot found is either SQL-bound, already numpy-bound, or beaten by a numpy
algorithm change that was measured before Rust was tried. Vendor tools (Quartus / Diamond) dominate
every gate's wall by two orders of magnitude.

Harness: `scripts/profile_stages.py` (child per stage, `os.wait4` rusage, `--cprofile` for hot-loop
share; results `tmp/profile_stages*.json`, log `tmp/logs/profile_stages.log`). Spike crate:
`tmp/rust-spike/` (not committed; recipe below). Box: 30 cores, python3.15t free-threaded, numpy 2.5.4,
rustc 1.97, other agents active (take walls as +-20%).

## Profile table (real inputs, one run each; cold-ish page cache)

| stage | input | wall s | CPU s | peak RSS | hot loop | share | kind |
|---|---|---|---|---|---|---|---|
| `cram_plane` decode | EP4CGX150 corpus image, 1.34 MB compressed -> 4.9 MB | 0.80 (decompress 0.34, keys 0.04) | 3.1 | 83 MB | `nibble_decode` + `crc16` | 68% | pure Python |
| `Dec.active` (asm) | 51.6 M entries / 17.3 M groups vs plane | 1.4-1.9 (+0.3-0.9 load) | 6.8 | 2.5 GB | `SparsePlane.has` searchsorted + `np.unique` | 66% | numpy |
| `ddb_routing.fanout` | routing.ddb 88 MB body | 2.0 | 4.4 | 860 MB | ptr-tag chain 0.07 + template walk 0.03 (pure Python) | 5% | numpy |
| `ddb_trace score` 3 designs | gx150_rb odd | 19.8 (~3 load + 5.6/design) | 21.9 | 3.7 GB | `Dec.active` x6 = 10.8 cum; `has` from `read_bits` 100 k calls 0.8 | 67% | numpy |
| `bit_inventory` | same image | 21.5 | 23.6 | 2.95 GB | `np.unique` (`_unique_hash`, 29 calls) 16.1 | 72% | numpy (algorithm) |
| `reach.py` fnirsi | 5,359 nets, 1.93 M pairs, 8 workers | 11.3 (BFS 0.3, upsert 6.0, startup+DELETE ~5) | 11.6 | 270 MB | SQLite `executemany` upsert | >= 55% | SQL |
| `reach.py` V02 | 4,341 nets, 2.65 M pairs | 17.4 (BFS 0.4, upsert 9.3) | 17.9 | 352 MB | same | >= 55% | SQL |
| `reach2.py` fnirsi | 1.93 M reach rows | 29.2 (reverse 17.7, ff_cones 9.5, crit 1.7) | 28.9 | 1.5 GB | `sqlite3.execute` 67% + `executemany` 9.5% | 77% | SQL |
| `reach2.py` V02 | 2.65 M rows | 48.4 (reverse 27.1, ff_cones 12.8, dominators 6.9) | 48.1 | 2.1 GB | same | — | SQL |
| `reach3` / `report` fnirsi | | 0.65 / 0.20 | | 74 / 62 MB | | | |
| `reach4` fnirsi, repl | | fails: kept DBs predate schema (5 columns absent) | | | | | |
| MachXO2 lift | Diamond construct `.config` | 0.50 (init 0.37, recover 0.045) | 1.0 | 170 MB | | | |
| ECP5 lift | 267 KB LFE5U-25F `.bit` | 8.1 (native decode 2.6, **init 4.3**, parse 0.08, recover 0.7) | 14.2 | 1.96 GB | `rgraph.wire` / `globalise_net` dict+set, already threaded | 53% | pure Python |
| lifter tests (108) | tests/ | 0.8 | 0.8 | 98 MB | | | |
| `corpus_register` cycloneiv | 10,840 build dirs | 3.2 | 1.7 | 110 MB | sha256 + toml + stat | | I/O |
| ledger page build | | 0.06 | | 20 MB | | | |
| specimen `diff` (forced/m9k `bits`) | two 4.7 MB raw rbf | 0.43 | | 103 MB | 2x `cram_plane` + `set()` | | |

- `Dec.active` is the shared hot call of every Cyclone IV sweep: 2x per specimen in `Solver.fired`, 1x per
  design in learn/score, 2x per design per tracer (54% of the tracer stage), 1x in the inventory.
- cProfile inflates pure-Python phases ~2x and makes the ECP5 init look like 138 s (threads); the
  unprofiled numbers above are the real ones.
- Nothing fails to fit: largest RSS seen 3.7 GB (tracer). The known 30 GB case (8 concurrent 85F ECP5
  lifts, `docs/ecp5-corpus.md`) is Python object graphs in `native_trellis/rgraph.py`; a Rust port of
  the routing graph would cut it but is a port of the whole graph builder, not a hot loop.

## Spike results (`tmp/rust-spike/ffi_check`, PyO3 0.30.1 + numpy 0.30, 151 lines)

| candidate | Python | numpy alternative | Rust | identical? |
|---|---|---|---|---|
| `nibble_decode` (1.34 MB -> 4.9 MB) | 0.143 s | n/a (sequential codec) | 0.0043 s (33x) | yes, bytes + leftover |
| plane keys from decompressed frames | 0.043 s (unpackbits) | — | 0.0056 s | yes, 320,332 keys |
| `Dec.active` | 1.373 s | **0.199 s (6.9x)**: dense bool plane + gather instead of searchsorted; mark-array instead of `np.unique` | 0.102 s 1 thread (13.4x; 1.9x over numpy); 0.137 s 8 threads | yes, on 4 images (19,562 / 18,032 / 18,551 / 10,785 groups) |
| `np.unique` on 2.85 M int64 | 1.20 s (`_unique_hash`) | **0.035 s sort+diff (34x)**, 0.050 s mark-array | not tried | yes |

- Build: cold 5.0 s wall / 14.7 s CPU, 777 KB `.so`, 102 MB `target/`. Incremental 0.2-0.3 s.
- Rust 8 threads slower than 1: the pass is memory-bound and the per-thread partial merge (17 M + 7 M
  counters) costs more than it saves. NoGIL parallelism belongs at the per-design level, where it already is.

## Ranked candidates

1. **`SparsePlane.has` -> dense bitmap** (numpy, not Rust). 6.9x on `Dec.active`, measured; removes the
   67% searchsorted share of the tracer and the 50% of `active`. Dense plane = 39 MB bool per design.
   Estimated tracer stage 20 s -> ~10 s, specimen `Solver` ~4 s -> ~1.6 s per specimen.
2. **`np.unique` -> sort-based unique** (numpy). 34x on the call; bit inventory 21.5 s -> ~6 s estimated
   (16 s of 22 s is in `_unique_hash`). Applies to `Dec.active` and `prepare` too.
3. Bitstream decode (`nibble_decode` + `crc16` + keys): Rust 33x, the only hotspot numpy cannot take.
   Saves 0.34 s per design; a design costs minutes in Quartus and the corpus passes are already
   NoGIL-threaded. Shortlist only if a 10 k-image decode-only pass becomes a routine step (10 k x 0.34 s
   = 57 min CPU -> 2 min).
4. `reach2` reverse pass (SQL `INSERT ... SELECT` 17-27 s): index `reachability(bitstream, dst)` and
   query it, or build the reverse map in memory from the rows `ff_cones` loads anyway. Not Rust.
5. `reach.py` upsert (6-9 s): `--replace` already deletes the label's rows, so a plain `INSERT` without
   `ON CONFLICT` (no probe per row) should ~2x it. Not Rust.
6. ECP5 lifter init 4.3 s (routing graph build): once per process; cache per device if it ever shows
   up per bitstream. Not Rust.

Rust shortlist after pricing alternatives: item 3 only, and it fails the "dominates a pipeline" test.

## Do NOT rewrite

- `reach.py` BFS: 0.3-0.4 s for 2-2.7 M pairs, 8 NoGIL threads; the stage is SQLite insert.
- `reach2` / `reach3` / `reach4` / `report`: SQL-bound (77% inside sqlite3) or sub-second.
- `ddb_routing.fanout`: 2.0 s total, 95% numpy; the pure-Python loops are 0.1 s.
- `Dec.active`: numpy fix first (6.9x); Rust adds 1.9x on a 0.2 s call.
- Bit inventory: `np.unique` choice, not language.
- MachXO2 / ECP5 / Gowin / Anlogic lifters: parse + recover is 0.05-0.8 s; every gate's wall is Diamond
  (`scripts/machxo2_gate.py`, `scripts/ecp5_gate.py`) or Quartus (corpus / specimen builds, minutes per design).
- `corpus_register` (I/O + sha256), ledger page (git calls), tests (0.8 s).
- Specimen diff / m9k helpers: `bits()` = `cram_plane` + `set()`, 0.4 s.
- Cyclone V codec: already Rust (`rust/bluebird`); nothing in Python calls the binary.

## Existing Rust: `rust/bluebird/` (896 lines)

- Standalone CLI (`bluebird roundtrip <die> <rbf>`, `bluebird route-counts <die>`), rusqlite bundled,
  reads `pluribus.db` (`cv_dies`, `cv_route_*`). No Python binding; no script invokes it. Build
  `cargo build --release`; tests `cargo test` (9/9, 0.5 s warm).
- Finding: both real-data tests (`corpus_bitstream_roundtrip`, `e50f_route_counts_are_plausible`) pass
  vacuously today — the corpus fixture dir is empty and `cv_dies` has 0 rows in the rebuilt
  pluribus.db; they skip with an `eprintln`, not a failure. Filed as an issue (see #144 thread).
- `native_trellis/` is pure Python despite the name (MachXO2/ECP5 geometry + routing graph).

## FFI under python3.15t (verified)

- **PyO3 0.30.1 + `numpy` 0.30 crate, `#[pymodule(gil_used = false)]`**: builds against this interpreter
  with `PYO3_PYTHON=$(which python3.15t) cargo build --release`; copy `target/release/lib<name>.so` to
  `<name>.cpython-315t-x86_64-linux-gnu.so` on `sys.path` (or `maturin build -i python3.15t`).
  `sys._is_gil_enabled()` stays `False` after import. Readonly numpy borrows are zero-copy; `py.detach`
  releases the interpreter for the hot loop. abi3 is not available on free-threaded builds, so the
  `.so` is pinned to 3.15t: rebuild per interpreter upgrade (pyo3 must support the new minor first).
- **ctypes to a cdylib**: also keeps the GIL off, no pyo3 version chase, but manual marshalling; fine for
  flat arrays (`a.ctypes.data_as`).
- **Standalone CLI + files** (bluebird model): zero FFI risk, pays serialisation; right for batch tools,
  wrong for a per-design call inside a sweep.
- Recommendation if a module is ever added: PyO3 extension in `rust/<name>/`, built by a
  `scripts/<name>_build.py` wrapper, imported lazily with the Python path kept as the test oracle.

## Recommended first spike (only if Rust is still wanted)

- `native_cycloneiv`: `nibble_decode` + `crc16`/`frame_ok` + plane keys (`cycloneiv_decompress` +
  `cram_plane`), ~200 lines, 33x measured on the codec.
- Acceptance: byte-identical `decompress()` output and identical `plane.keys` against the Python path on
  all 10,842 corpus rbf + the 14 third-party images; Python path stays as the oracle in `tests/`.
- Cost: cargo + pyo3 in CI, interpreter-pinned `.so`, rebuild on every Python minor; `scripts/` fallback
  to Python when the module is absent.
- Before that: land candidates 1 and 2 (numpy) — they give more wall back than the Rust spike would.

## Cost / maintenance

- Every Rust module = second implementation to keep bit-identical, a toolchain in CI, and an
  interpreter-pinned artefact. Worth it at >= 10x on a stage that dominates a sweep; not at 1.9x over numpy
  or 0.3 s per design under a multi-minute vendor build.
- Measured data lives in `tmp/profile_stages*.json` (regenerable: rerun the harness); numbers above are
  the 2026-10-29 run on the inputs named.
