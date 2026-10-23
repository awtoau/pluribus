# Cyclone V block-mux import — status

Imports Mistral's block-mux ground truth (21 `data/*-mux.txt` files) into
`cv_block_muxes` (`schema.py`). Covers LAB common logic, M10K modes, DSP
mux usage, GPIO/PLL/HSSI mux selection — real documented gaps in the
Cyclone V corpus, all previously absent from the DB. Companion to the
routing-node import (`cv_route_muxes`/`cv_route_lines`/`cv_route_drivers`/
`cv_p2r`/`cv_p2p`, `docs/bluebird.md`), which covers the general
interconnect fabric, not the muxes inside a block.

Script: `scripts/cyclonev_db_import_blockmux.py`. Logs to
`./tmp/logs/cyclonev_db_import_blockmux.log`.

## Scope vs. the prior scoping

Everything in the original scoping was confirmed against the real files
and the real generator (`tools/mux_to_source.py`), not assumed:

- Three RAM spaces confirmed: `opt-mux.txt` → ORAM, 17 files → PRAM, 5
  files (lab/mlab/m10k/dsp/hps_clocks) → CRAM. `opt-mux.txt` IS `is_2d=True`
  in the real `load_mux_data("opt", {'g':1}, True)` call — ORAM positions
  are `x.y` pairs too, same coordinate shape as CRAM; oram/pram/cram is a
  RAM-*identity* distinction on the C++ consumer side, not a coordinate-
  shape distinction on the producer side.
- `tmap` (span-count-per-subtype) reproduced verbatim from
  `mux_to_source.py` lines 219-240 — confirmed non-uniform within a file
  (dsp: `g=1,c=8,d=12`), confirmed to match every subtype actually present
  in every file (checked by listing distinct subtype tokens per file
  against each file's declared tmap — no file uses an undeclared subtype).
- `variantmap` overrides reproduced verbatim: gpio
  `{'x':1,'X':0,'s':1}`, pma3 `{'t':1,'b':0}`, everything else -1.
  Cross-checked against the real compiled struct's trailing field for
  gpio's `drive_strength` (X→0, x→1) and `enable_serdes_loopback` (s→1).
- `lab_expand()` reproduced verbatim (mux_to_source.py lines 86-120),
  including the MLAB 64-bit `lut_mask` split branch. Hand-checked against
  a live run of the real generator before writing the importer, then
  cross-checked again post-import — see Verification below.
- Not per-die, confirmed by reading the loader: `load_mux_data()` takes no
  chip/die parameter, `mux_to_source.py`'s CLI takes only a data-dir, and
  `libmistral/cv-bmux-data.cc` (the compiled output) is one set of
  file-scope `bm_*[]` statics with no per-die indirection anywhere in
  `cv-bmux.cc`/`cv-rmux.cc`. These are block-mux *definitions* — identical
  bit encodings in every Cyclone V die; only block *counts* vary per die
  (via `cv_dies`/the tile grid), not what a given mux decodes to.

## Surprise found during this session (not in the original scoping)

**Mux name is not a unique key — not even `(file, subtype, mux)`.**
Two cases in the real data have two structurally distinct mux definitions
sharing the identical subtype+name within one file:

- `hssi-mux.txt`: `i pcs8g_digi_tx_plane_bonding_consumption` appears
  twice, at different bit positions (lines 204 and 360).
- `m10k-mux.txt`: `g b_dmy_delay` appears twice, at different bit
  positions (lines 26 and 55).

The real C++ enum generator (`enum_add()`) collapses these to one shared
enum *name* for lookup purposes, but `dump_muxes()` still emits one
*struct row* per source line — no merge. `cv_block_muxes` therefore has no
`UniqueConstraint` on `(dump_target, mux)` or even `(dump_target,
subtype, mux)`; identity is `id` plus the non-unique indexes, matching
the precedent `cv_route_muxes` already set for the same reason (repeating
rnode coordinates, not names, there).

**`cmuxv-mux.txt`/`cmuxh-mux.txt` each feed two distinct compiled arrays**
(`cmuxvr`/`cmuxvg`, `cmuxhr`/`cmuxhg`) from one source file, split by a
subtype filter (`r`/`R` vs `g`/`G`) in `dump_muxes()`'s own call site —
not a per-file 1:1 mapping like every other file. `dump_target` exists
specifically to carry this: it is the compiled array name, not always the
source file's base name. `cmuxc-mux.txt` is the one apparent exception
that isn't one: its single `dump_muxes("cmuxcr", cmuxc, 1, counters)` call
has no filter at all, so all of cmuxc's R/Y/r subtypes land in one
`cmuxcr` target — the trailing 'r' in that name is cosmetic, not a filter
marker.

**Default suffix on `r`/`b` stype is parsed as HEX, not decimal** — e.g.
`opt-mux.txt`'s `start_up_clock` has suffix `3f`, giving default 63
(`int('3f', 16)`), not 3 or 35. Confirmed by running the real generator,
not by reading the loader code alone (hex-vs-decimal parsing bugs are
exactly the kind of thing worth a cross-check rather than a code read).

## Table shape

One table, `cv_block_muxes` — same one-table-plus-JSON convention
`cv_route_muxes` established: value-mappings (`values`, stype m/n) and
per-span bit-position rows (`bits`) are JSON arrays on the parent row, not
child tables. 4,650 source lines total (largest file, hip-mux.txt, is 900
lines) is nowhere near route-table scale (cv_route_muxes: ~695k rows for
one die alone) — normalizing bits/values into child tables would add
thousands of rows for no query this project currently needs that the JSON
columns don't already serve, so the same convention applies unchanged.

No `die` foreign key — these rows are device-family-wide, confirmed above,
unlike `cv_route_muxes` et al.

## Verification

Ground truth: a live run of `tools/mux_to_source.py mux data` (the real
generator, not re-derived or guessed), parsed back out of its output and
diffed against every imported row — not sampled, all 1416 rows:

- **Row counts**: all 24 `dump_target`s match the real `bm_<target>[]`
  array lengths exactly (1416 total).
- **Structural signature** (stype, bcount, span, value-entry count,
  variant) matches as a multiset for every target.
- **Actual bit positions**: reconstructed from the real compiled
  `bmux_oram_bpos`/`bmux_pram_bpos`/`bmux_cram_bpos` flat arrays using
  each row's real `bit_offset`, and diffed against the imported `bits`
  JSON — zero mismatches across all 1416 rows.
- **Value-mapping text**: reconstructed from the real compiled
  `bmux_sel_entries`/`bmux_num_entries` flat tables using each row's real
  `entries_offset`, diffed against imported `values` — zero mismatches.
- **Defaults**: real `def` field (-2 sentinel = no default) diffed against
  imported `default_value`/`default_value_idx` — zero mismatches.

Spot-checked by hand before the automated cross-check (lab's `tdff0`,
`b_feedback_sel`; mlab's `lut_mask` 64-bit split; dsp's `coef_b`;
gpio's `drive_strength` X/x variant split) to build confidence in the
transliteration before trusting the bulk diff.

## Not done this session (explicitly out of scope)

- No `cv-bmux.cc`/`cv-rmux.cc` runtime CRAM-bit decode logic — this
  imports the mux *definitions* only, not a bitstream-to-mux-setting
  decoder. Real future work, same status as the Rust routing port
  (`docs/bluebird.md`).
- No Quartus-fuzzing campaign to make this pluribus's own independent
  ground truth (same bootstrap/verification-source caveat as
  `cv_route_muxes`) — LAB/M10K/DSP/GPIO/PLL/HSSI muxes remain un-fuzzed by
  pluribus itself; this import only gets Mistral's existing ground truth
  into queryable rows.

## Memory safety

All 21 files total 4,650 lines (largest: hip-mux.txt, 900 lines) — nothing
like the routing import's multi-million-line files that caused the two
OOM kills that session. No streaming/batching needed; whole dataset
parses and inserts in one pass in well under a second. Still gated behind
the same `psutil.virtual_memory()` check (`--max-ram-pct`, default 85 —
never 50, see `cyclonev_db_import_routes.py`'s own note on why) before the
insert, for consistency with the established pattern.

## Regression

- `python3 -m pytest tests/test_sqlite.py -q` — 8/8 pass.
- `schema.py` diff is purely additive (92 insertions, 0 deletions,
  confirmed via `git diff --stat`).
- Full Hantek/Lattice pipeline (`scripts/run_pipeline.py --board
  boards/aw2-2d82auto --label V02`), run from a worktree rooted directly
  under `/mnt/2tb/git/` so the board.toml's relative `../../../awto-2000`
  paths resolve: exact known-good baseline reproduced, `2611/1280 (203%)
  LUTs, 1108 FFs, 4341 nets`.
