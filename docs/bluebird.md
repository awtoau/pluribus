# Bluebird — Cyclone V bitstream engine

- Bluebird is pluribus's own Cyclone V engine (`rust/bluebird/`, binary `bluebird`), replacing Project Mistral (Ravenslofty/mistral).
- Mistral is the starting point only: its data seeds the tables, and each part is replaced once Quartus fuzzing (#103) has verified or corrected it.
- Acceptance test: full loop — Verilog -> Quartus -> bitstream -> lift -> Verilog -> compare with Quartus's post-fit netlist.
- Renamed from `rust/cyclonev/` on 2026-10-23.
- Formats: adopt Project X-Ray's, don't invent (Dan, 2026-10-23). Clones: `/mnt/2tb/git/prjxray` (no db submodule), `/mnt/2tb/git/fasm`.
  - FASM for the feature-level bitstream text (`fasm/docs/specification/`).
  - `segbits_<tile_type>.db`: `<feature> <bit>...`, `!` = must be 0. Bit = tile-relative `<dx>_<dy>` (Cyclone V CRAM is x/y, not X-Ray's frame/word).
  - `tilegrid.json`: per tile type/grid/sites/bits; Cyclone V's CRAM / PRAM / ORAM map onto X-Ray's per-bus `bits` entries.
  - Correlation: X-Ray `tools/segmatch.cc`, tags from Quartus `.vo` + `-show_routing`.
  - FASM parser needs `textx` (pure Python) for python3.15t; not installed yet.

## Mistral's data/*.txt(.xz) is a BOOTSTRAP/VERIFICATION source, not permanent

Every table in this doc sourced from Mistral's plain text (`cv_dies`,
`cv_pram_strips`, and this session's `cv_route_muxes`/`cv_route_lines`/
`cv_route_drivers`/`cv_p2r`/`cv_p2p`) is borrowed ground truth, useful right
now for building and testing a real Rust node/mux layer, but not meant to be
pluribus's permanent source of Cyclone V routing/device truth. The
independent, longer-term path for the same ground truth is a Quartus-based
fuzzing campaign — compile known test designs that exercise specific
routing patterns, decompile, cross-check against the known design — same
method already used for DSP operational modes
(`scripts/cyclonev_dsp_fuzz.py`) and for the Lattice side
(`scripts/run_prjtrellis_fuzz.py`). That campaign is explicitly NOT
attempted in either session so far — the routing-pattern space is far
larger than DSP modes — and is real future work, not a gap in what's below.

## Standing requirement: round trip, not one-directional decode

**Every Cyclone V Rust deliverable in this project must be verified by full
round trip, not by decode-and-eyeball.** Same discipline pluribus already
applies to its Lattice lifters (ECP5 `scripts/ecp5_roundtrip.py`, MachXO2
fuzzer compat checks: place → decompile → recompile → re-decompile → diff).
For the compression codec specifically: decompress → recompress →
decompress again, bit-exact, on real device data — not just "it decoded
without crashing." Apply this to cv-bmux/cv-rmux work in later sessions too.

## Why data-driven, not hand-ported C++

Mistral's per-die data (`cvd-*.cc`, ~540 lines total) is generator output,
not hand-written: `generator/` (3,063 lines of C++) compiles it from plain
text under `mistral/data/*.txt(.xz)`. Pluribus skips that codegen step
entirely — the Python importer reads the same plain text (and, for
geometry fields with no separate text source, `cvd-*.cc`'s own regular
struct-initializer layout) straight into SQLite. Same model as
`device-db/` for Lattice: vendored data, pristine, queried by the engine,
never hand-edited.

## What's done this session

**Schema** (`schema.py`, after `device_fingerprints`):
- `cv_dies` — one row per die (7 total: e50f, gt75f, gt150f, gt300f, gx25f,
  sx50f, sx120f). Cram/tile geometry, frame_size, postambles, pram_sizes,
  noedcrc_zones, x_to_bx, column_types. Everything `die_info` carries that
  `cv-files.cc`'s compression codec needs.
- `cv_pram_strips` — PRAM (fixed-block-position) strips, one row per
  `data/<die>-pram.txt` line (1,696 rows across all 7 dies).

**ETL** (`scripts/cyclonev_db_import.py`):
- Parses `libmistral/cvd-<die>.cc` (die geometry — regular struct
  initializer, identical layout per die, no separate plain-text source for
  these specific fields) and `data/<die>-pram.txt` directly (PRAM strips —
  genuinely the plain-text generator input, mirroring `generator/pram.cc`'s
  own grammar, including its `-` "no instance, var follows" case).
- Always-rebuild per die (delete + reinsert), `db.die()` fail-fast on any
  parse mismatch (missing field, length mismatch against `tile_sx`, etc).
- All 7 dies import cleanly. Values cross-checked against `cvd-e50f.cc`
  (cram 4958×3928, tiles 55×46, frame_size 129, postambles 102/388) —
  match.

**Rust crate** (`rust/bluebird/`, binary `bluebird`):
- `rusqlite` (bundled SQLite) chosen over `sqlx` — synchronous CLI/batch
  tool, no async runtime used anywhere else in the call graph.
- `src/db.rs` — reads `cv_dies` into a `DieInfo` struct.
- `src/codec.rs` — ports `cv-files.cc` exactly, both directions:
  - `nibble_decompress`/`nibble_compress` — the nibble zero-suppression
    codec (NOT RLE).
  - `unpack_cram_bits`/`pack_cram_bits` — the y-position bit-folding
    arithmetic (`ya`/`yb` split, `pos = 224 + (31^yb) + 32*ya`) that sits
    around the codec in `rbf_load`/`rbf_save`.
  - 7 unit tests: empty/all-zero/all-0xff/random/sparse nibble round trips,
    a compress-stability check, and a CRAM bit-fold round trip at real
    e50f scale (cram_sy=3928, frame_size=129 — a synthetic small
    `cram_sy` broke the `ya`/`yb` split out of bounds; the geometry only
    stays in range at real die scale).
- `src/main.rs` — `bluebird roundtrip <die> <path>` CLI, plus an integration
  test (`real_dji_bitstream_roundtrip`) that runs the same check as part of
  `cargo test`.

## What's proven

Ran against the real DJI C1 e50f bitstream
(`/mnt/2tb/git/awto-dji/firmware/unpacked/C1_FW_V01.06.0000/m2001.depack.bin`,
2,119,888 bytes):

- CRAM region located at file offset 34164 (via the same
  `oram_frame_bytes + pram_frame_bytes * pram_blocks` arithmetic
  `rbf_load` uses).
- Nibble-decompressed 2,085,724 compressed bytes → 2,597,992 frame bytes.
- Unpacked 19,475,024 CRAM bit positions; 1,152,281 set (~6% density —
  plausible for real fabric config, not all-zero or implausibly dense).
- **CRAM fold round trip**: `unpack(pack(cram_bits)) == cram_bits`,
  bit-exact over all 19,475,024 positions.
- **Nibble codec round trip**: `decompress(compress(decompress(original)))
  == decompress(original)`, bit-exact.
- Both checks run as part of `cargo test` (`real_dji_bitstream_roundtrip`),
  not only by manual CLI invocation.

Caveat found and recorded, not hidden: mistral's own `mistral-cv cycle`
(its CLI's `rbf_load` → `rbf_save` round trip) does **not** reproduce this
file's CRAM content exactly on first load — but cycling its own output a
second time IS a stable fixed point (byte-identical). This means mistral
defaults some bitstream options it can't recover from this file (no IDCODE
in a Cyclone V raw bitstream — consistent with `device_fingerprints`'
awto-dji#3 finding), not a codec bug. The nibble codec and CRAM fold
arithmetic ported here are option-independent pure data transforms, and
this session's round-trip checks validate them directly rather than
through mistral's own lossy CLI round trip.

Not proven: byte-identical re-encoding of the *original* compressed region
(our re-compress only encodes the CRAM-fold bits this module models, not
the CRC/padding bytes that coexist in the same frame — see "Known gaps"
below). What's proven is losslessness of the transforms this module
actually implements, which is the honest scope.

## Known gaps / out of scope as of the first session

- **ORAM header, PRAM framing, per-frame CRC/EDCRC trailer**: not parsed or
  generated. `main.rs`'s frame-byte comparison against the real
  decompressed buffer is informational-only for this reason (framed bytes
  are not expected to match byte-for-byte; only the CRAM-fold bit
  positions are modeled and checked).
- **cv-bmux.cc (1,132 lines) / cv-rmux.cc (1,549 lines)**: NOT attempted.
  These need a binary-format redesign (Mistral's `reinterpret_cast` over
  compiled-in blobs, pointer arithmetic over `rnode_object`/`data_header`
  packed structs) — the information is understood, the memory-layout
  tricks are not safe-Rust-portable 1:1. Still real future work (see
  "Next-session scope" below) — importing the routing/mux tables (this
  session's work) was a prerequisite step, not this step itself.
- **Package/pinout tables** (`e50f-pkg.txt`): not imported.
- **Other 6 dies' codec path**: only e50f tested against real data in the
  first session (no other die has a real-world bitstream fixture on hand).
  The codec and fold arithmetic are die-parametric (geometry comes from
  `DieInfo`, not hardcoded), so this is a fixture-availability gap, not a
  code gap — worth a synthetic round-trip test per die as a cheap
  confidence check.

## Second session (2026-10-23): routing-node tables imported

Next-session scope item 1 from the first session ("Import routing node
tables... likely 2-3 new tables"). **That estimate was wrong**: the real
grammar is 5 distinct plain-text files/formats, not 2-3, each read from its
`generator/*.cc` PRODUCER source (same discipline as the first session's
`cyclonev_db_import.py` reading `generator/pram.cc`, not reverse-engineering
`cvd-*.cc`'s compiled layout) — `routes.cc`, `nodes.cc`, `rdriver.cc`,
`p2r.cc`, `p2p.cc`.

**Schema** (`schema.py`, 5 new tables after `cv_pram_strips`):
- `cv_route_muxes` — one row per `data/<die>-r.txt.xz` line: a destination
  rnode's mux pattern (0-69, or 70-73 for pattern 6's 4 sub-variants, or
  NULL for a `-` "no mux" line) plus its `fw_pos` cram position and a JSON
  `sources` list (slot → source rnode).
- `cv_route_lines` — one row per `data/<die>-l.txt.xz` line: a source
  rnode's electrical line model (tc1/tc2/r85/capacitance/length) plus a JSON
  `targets` list (fan-out, each either a downstream rnode+subslot or a bare
  capacitance tap).
- `cv_route_drivers` — one row per `data/<die>-d.txt.xz` line: an rnode's
  left/right named driver-model pair (names only, e.g. `"gout_labcell_a"` —
  the electrical driver MODELS themselves live in Mistral's separate
  `driver-models.txt.xz` and are not imported, out of scope for routing
  topology).
- `cv_p2r` — one row per `data/<die>-p2r.txt` port-instance-bit entry
  (block port ↔ routing node).
- `cv_p2p` — one row per `data/<die>-p2p.txt` line (direct port-to-port
  connection bypassing the routing fabric).

Repeating per-row arrays (mux sources, line targets) are stored as JSON on
the parent row, not exploded into child tables — same convention `cv_dies`
already uses for `pram_sizes`/`x_to_bx`. A fully normalised design would add
~24M rows for e50f's routing layer alone (avg 17 sources/mux, 19
targets/line) with no query this project currently needs that JSON doesn't
already serve.

Two grammar edge cases the naive reading misses (both confirmed against
real e50f data, not assumed):
- A `-` routes line ("no mux pattern") can still carry a fixed source list
  — 82,932/695,446 e50f rows, e.g. a sector-clock-buffer stage with exactly
  one hardwired input and no actual mux bits.
- A p2p pnode's `:porttype` suffix is optional (`nodes.cc`'s `lookup_p`
  consumes the instance digit unconditionally, before the `:port` check) —
  272/1,755 e50f lines are a bare block+instance reference with no port,
  e.g. `DQS16.000.016.0`.

**ETL** (`scripts/cyclonev_db_import_routes.py`) — verified against real
e50f data, row counts matching the source files exactly:

| table | e50f rows | matches |
|---|---|---|
| `cv_route_muxes` | 695,446 | `-r.txt.xz` line count exactly |
| `cv_route_lines` | 625,862 | `-l.txt.xz` line count exactly |
| `cv_route_drivers` | 839,698 | `-d.txt.xz` line count exactly |
| `cv_p2r` | 8,418 | `-p2r.txt`'s 1,536 lines × inst/bit expansion |
| `cv_p2p` | 1,755 | `-p2p.txt` line count exactly |

Also verified on gt75f (a larger die): routes/lines/rdriver/p2p again match
the real file line counts exactly (1,082,170 / 973,813 / 1,308,881 / 3,395).

**Relationship to the m2001 design's 70,007 resolved arcs** (first
session's real DJI fixture decode): these are different data layers, not
comparable 1:1. `cv_route_muxes`/friends are device-wide routing CAPACITY —
every mux Mistral's fuzzer found on the whole e50f die, most of them never
used by any one design. The dominant rnode types by row count (`GOUT`
201,296, `TD` 138,208, `H6` 115,456, `H3` 57,200, `V2` 53,572 of 695,446
total muxes) are exactly the general-purpose fabric routing switch points
you'd expect a device-wide table to be dominated by. m2001's 70,007 arcs are
one design's actual ROUTES — a small, design-specific subset of what this
table says the device CAN route. Neither number should match the other;
both are real and consistent with what they each measure.

### The OOM incident and the memory-safety redesign

The first version of the ETL threaded across dies (`die_workers=2..4`) AND
parsed each huge file whole into one Python list before any row reached the
DB. Running all 7 dies that way triggered **systemd-oomd to kill the entire
host IDE twice** (confirmed via `journalctl`, ~11 minutes apart) — multiple
dies' full parsed row lists live in memory concurrently (gt300f's
`-r.txt.xz` alone is 3.72M lines) with zero backpressure; a worker-COUNT cap
doesn't bound actual RAM, which scales with data size, not thread count.
Same root-cause class as a separate, unrelated incident that hit this
session's Quartus-compile verification harness
(`scripts/cyclonev_verify_all.py`), fixed there with a `psutil` memory gate.

Redesign, verified correct and safe:
1. **Dies run strictly sequentially**, never concurrently — this is a
   one-time bootstrap import, not a hot path worth trading memory safety
   for parallelism on.
2. **Streaming batches**: each large file is read and inserted in bounded
   batches (`--batch-lines`, default 100,000) instead of parsed whole into
   one list first. Peak memory is one batch's rows, not one die's.
3. `threading.Thread` + `queue.Queue` (reach.py's exact pattern) applies
   **within** a batch — splitting its lines across `--chunk-workers`
   threads for parsing, verified safe because every record in all 5
   grammars is exactly one line (no state carried across `\n`, confirmed
   reading each `generator/*.cc` parser).
4. A `psutil.virtual_memory().percent` gate (`--max-ram-pct`, default 50%,
   same pattern as `cyclonev_verify_all.py`'s `run_producer_consumer`)
   blocks claiming the next batch/die while RAM is already over budget.

**Empirically verified, not just "looks safer":** re-ran the redesigned
e50f import and got byte-identical row counts to the pre-redesign run
(695,446/625,862/839,698/8,418/1,755), with the process's own RSS measured
(via a live `ps`/`free` monitor during the run) staying in the 135MB-1.4GB
range throughout — never the multi-GB unbounded growth the old design had.
During a full 7-die run, the gate was observed firing for real against
genuine (unrelated) host memory pressure — a 16GB Windows VM running
concurrently on the same machine for other work — logging `RAM at 53% >=
50% -- pausing before next batch of gt150f-l.txt.xz`, with the import
process's RSS confirmed pinned (not growing) for the full pause duration.
The gate is appropriately conservative: it fires on *any* system memory
pressure, not just pressure this script itself causes, which is the safer
direction to be wrong in for a one-time bootstrap script.

**Threading benefit, measured** (pre-redesign baseline, chunk-parsing a
whole e50f file single-threaded vs 8 threads — the batch redesign doesn't
change the per-batch parse speedup, only the memory profile):
- `-r.txt.xz` (695,446 lines): 17s → 5.2s
- `-l.txt.xz` (625,862 lines): 17s → 8.0s
- Total import wall-clock: 52.7s → 39.6s (smaller than the parse-only
  speedup because DB insert is serialized by SQLite regardless of thread
  count — expected, not a bug).

**Rust side**: `rust/bluebird/src/rnodes.rs` — a read-only query layer
(`route_counts`, `lookup_mux`) over the 5 new tables, plus a `cyclonev
route-counts <die>` CLI command and a real-data test
(`e50f_route_counts_are_plausible`) asserting the exact e50f row counts
through the Rust reader (all passing: 9/9 `cargo test`). This does **not**
implement any `cv-bmux.cc`/`cv-rmux.cc` logic (resolving a mux's selected
source against decoded CRAM bits, walking the net graph) — it proves the
imported data is queryable and correctly sized from Rust, which is what
this session's scope allowed for. The Rust-side work this session produced
is genuinely small and mostly sequential (two DB queries) — no artificial
multithreading was forced onto it; the real multithreading this session
added is in the Python ETL (batch-internal chunk parsing), honestly
reported as such rather than padded out on the Rust side for appearance.

## Next-session scope (realistic)

1. Design the Rust binary-format replacement for `cv-bmux.cc`/`cv-rmux.cc`
   (the actual "needs real design work" ~2,681 lines) — now that node/mux
   data is in SQLite (this session's work), this is query + logic over
   `cv_route_muxes`/`cv_route_lines`/`cv_route_drivers`, not pointer
   arithmetic over blobs. Still genuinely out of reach in one session —
   this is the real remaining size of the port.
2. Port ORAM header + PRAM framing + CRC/EDCRC trailer so a full `.rbf` can
   be loaded and re-saved byte-identical to a mistral-produced reference
   (not just the CRAM-fold core the first session proved).
3. Add synthetic per-die round-trip tests for the other 6 dies' codec path.
4. Run the full 7-die routing import to completion and record final row
   counts for all 7 dies (the run that validated the memory-safety redesign
   this session was repeatedly paused by an unrelated 16GB VM on the shared
   host — e50f and gt75f fully completed and verified exact-match, gt150f
   partially through when last checked; the design is proven correct and
   safe, this is "let it finish," not an open question).
5. Longer-term, real alternative to depending on Mistral's data/ tree
   indefinitely: the Quartus-fuzzing-campaign path described at the top of
   this doc. Not attempted in either session — flagged as real future work,
   not a gap in what's done.
