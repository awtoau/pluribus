# Cyclone V Rust port — status

Altera/Intel Cyclone V support for pluribus, ported from Project Mistral
(Ravenslofty/mistral, `/mnt/2tb/git/mistral`). Scoped across two research
passes + this implementation session (2026-10-23).

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

**Rust crate** (`rust/cyclonev/`, binary `cyclonev`):
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
- `src/main.rs` — `cyclonev roundtrip <die> <path>` CLI, plus an integration
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

## Known gaps / out of scope this session

- **ORAM header, PRAM framing, per-frame CRC/EDCRC trailer**: not parsed or
  generated. `main.rs`'s frame-byte comparison against the real
  decompressed buffer is informational-only for this reason (framed bytes
  are not expected to match byte-for-byte; only the CRAM-fold bit
  positions are modeled and checked).
- **cv-bmux.cc (1,132 lines) / cv-rmux.cc (1,549 lines)**: NOT attempted.
  These need a binary-format redesign (Mistral's `reinterpret_cast` over
  compiled-in blobs, pointer arithmetic over `rnode_object`/`data_header`
  packed structs) — the information is understood, the memory-layout
  tricks are not safe-Rust-portable 1:1. Next session's real scope.
- **Routing node tables** (`data/<die>-r.txt.xz`, `-l.txt.xz`, `-p2r.txt`,
  `-p2p.txt`, etc.): not imported into SQLite. These are the cv-bmux/
  cv-rmux data dependency — importing them is likely a prerequisite for
  that work, not a separate later step.
- **Package/pinout tables** (`e50f-pkg.txt`): not imported.
- **Other 6 dies' codec path**: only e50f tested against real data this
  session (no other die has a real-world bitstream fixture on hand). The
  codec and fold arithmetic are die-parametric (geometry comes from
  `DieInfo`, not hardcoded), so this is a fixture-availability gap, not a
  code gap — worth a synthetic round-trip test per die next session as a
  cheap confidence check.

## Next-session scope (realistic)

1. Import routing node tables (`data/<die>-r.txt.xz` etc.) into new
   `cv_rnodes`/`cv_muxes`-style tables — likely 2-3 new tables, largest
   single piece of remaining data-driven work.
2. Design the Rust binary-format replacement for `cv-bmux.cc`/`cv-rmux.cc`
   (the actual "needs real design work" ~2,681 lines) — once node/mux data
   is in SQLite, this is query + logic, not pointer arithmetic over blobs.
3. Port ORAM header + PRAM framing + CRC/EDCRC trailer so a full `.rbf` can
   be loaded and re-saved byte-identical to a mistral-produced reference
   (not just the CRAM-fold core this session proved).
4. Add synthetic per-die round-trip tests for the other 6 dies.
