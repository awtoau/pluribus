# Python perf pass (#145)

Python/numpy fixes from `docs/rust-candidates.md` (measured in #144). Rust not used. Outputs bit-identical to before.

## Before / after (2026-10-29, EP4CGX150 poseidon image, one run each, box shared, +-20 %)

Harness: `scripts/perf_pass_profile.py` (profile_stages under a memory lease; before = legacy env switches).

| stage | before | after | gain | peak RSS |
|---|---|---|---|---|
| `cram_plane` total (decompress + keys) | 0.346 s | 0.073 s | 4.7x | 80 -> 165 MB |
| `decompress` alone | 0.332 s | 0.084 s | 4.0x | |
| `Dec.active` warm (2nd call, per design) | 1.70 s | 0.31 s | 5.5x | |
| `Dec.active` cold (1st call: gather index + bitmap built) | 1.99 s | 0.86 s | 2.3x | 2.54 -> 2.11 GB |
| `Dec.load` | 0.60 s | 0.31 s | | |
| `asm_active` stage wall | 4.81 s | 1.76 s | 2.7x | |
| `ddb_trace score` 3 designs wall | 16.6 s | 7.91 s | 2.1x | 3.70 -> 3.30 GB |
| `prepare()` wall | 18.6 s | 14.6 s | 1.3x | |
| `np.unique` 2.85 M int64 -> `fastops.unique` | 1.53 s | 0.031 s | 49x | |

Per image (A/B script, GX150 corpus design, 4.9 MB uncompressed): `decompress` 0.168 -> 0.0145 s (11.6x, CRC walk only);
`cram_plane` 0.186 -> 0.032 s (5.8x). Compressed third-party (1.4 MB): `decompress` 0.31 -> 0.045-0.057 s (5.5-7x).
Full A/B pass over 759 images: decompress 82.0 -> 7.6 s, plane 91.6 -> 17.1 s.

## What changed

- `SparsePlane.has`: dense bool bitmap (`dense()`, 39 MB, cached per plane) + gather; used for >= 65536 queries.
  `PLURIBUS_PLANE_HAS=searchsorted|dense|auto`.
- `Dec.active`: cached per-entry bitmap slot index (`_flat`, 51.6 M int32 = 206 MB, plane-shape keyed) -> one gather per design;
  mark array replaces `np.unique(e_ukey[s])`. `PLURIBUS_ACTIVE=legacy` or `active(plane, method="legacy")`.
- `scripts/fastops.py`: `unique`, `unique_counts`, `unique_inverse`, `unique_rows2_inverse`, `mark_unique` (sort + diff).
  Same values, dtype, ascending order, inverse/counts indexed in that order. `PLURIBUS_UNIQUE=legacy` routes to `np.unique`.
  Adopted in `prepare()`, `afx_map`, `Dec.active`.
- `scripts/cycloneiv_decompress.py` (edited although outside the first file list; it owns the codec):
  - `frames_ok_np` / `cram_walk`: CRC-16 of all frames at once, one table step per byte column (794 steps over 6154 frames).
  - `nibble_decode_fast`: see below. `nibble_decode_scalar` is the old loop (also the odd-tail path). `PLURIBUS_DECODE=scalar`.
- `scripts/cycloneiv_corpus.py` `cram_plane`: keys from the nonzero bytes only (`np.nonzero` on the byte plane, bits expanded
  for those bytes), `cram_plane_scalar` = old per-frame build.
- `ddb_trace`: no edit needed; it reaches the new paths through `Dec.active` / `plane.has`.

## Is the nibble decoder frame-independent?

- No. Record length comes from its key; no resync marks; output frame boundaries do not map to input positions without decoding.
  The stream is sequential by construction.
- Not parallelised across frames/threads. It is a pointer chain on the nonzero nibbles (86 % of nibbles are zero keys,
  next(key) = first nonzero nibble at/after key + 1 + NV[key]); the chain is listed by pointer doubling
  (log2 m gathers, m = 380 k nonzero nibbles), payloads gathered, scattered by key index.
- Truncated final record (odd Quartus tail) is handed to the scalar loop at the exact nibble.
- 4.9 MB output: 0.159 s -> 0.041 s (3.9x).

## A/B verification (all 0 differences)

- `Dec.active` dense vs legacy: 11 images (4 poseidon, neptuno_cgx150_mc2, 6 gx150_rb), identical gids / grec / block ids and dtypes;
  `has` dense vs searchsorted on 300 k random in/out-of-range queries, int32 + int64. Fired groups 14,133-48,080.
- `prepare()`: all 11 output arrays identical to the on-disk set (new and `PLURIBUS_UNIQUE=legacy`).
- Decode: `scripts/perf_pass_verify.py decode --corpus 420` = 759 images vs frozen `tests/ref_cycloneiv_decompress.py`:
  byte-identical `decompress()` output and info dict, identical plane keys/shape. Mix: all 17 third-party sources (incl. 8 compressed;
  EP4CE6/10/15/55/115, EP4CGX150), 440 EP4CE6, every 29th GX150 corpus design.
- Tests: `tests/test_fastops.py`, `tests/test_cycloneiv_decompress.py` (40 random streams, every truncated-tail key, CRC walk with a bad frame).
- `ddb_trace score` output lines identical before/after.
- Not covered: the remaining ~10 k GX150 corpus rbf (same code path, same format); compressed images beyond the 8 third-party ones
  (corpus builds are uncompressed).

## Replacements for `scripts/cycloneiv_bit_inventory.py` (file had uncommitted edits elsewhere; not touched)

Add `import fastops` after the `scripts` sys.path line (24), then:

| line | old | new |
|---|---|---|
| 99 | `np.unique(np.asarray(flat, np.int64))` | `fastops.unique(np.asarray(flat, np.int64))` |
| 103 | `np.unique(prev[~free], return_counts=True)` | `fastops.unique_counts(prev[~free])` |
| 237 | `np.unique(np.asarray(pos[s:s + CH])[~ok])` | `fastops.unique(np.asarray(pos[s:s + CH])[~ok])` |
| 238 | `np.unique(np.concatenate(dropped_pos))` | `fastops.unique(np.concatenate(dropped_pos))` |
| 279 | `inv.cls[np.unique(spec_cells)]` | `inv.cls[fastops.unique(spec_cells)]` |
| 280 | `np.unique(prior[prior > 0], return_counts=True)` | `fastops.unique_counts(prior[prior > 0])` |
| 324 | `setmask[np.unique(spec_cells)]` | `setmask[fastops.unique(spec_cells)]` |

Lines 99 and 238 dominate (2.85 M-element calls). Expected inventory 21.5 s -> ~6 s (not measured here).
Other callers of `Dec.active` / `cram_plane` (specimens, phys_trace, li_map, asm_tables, image_demand) pick up the speed-up with no edit.

## Remaining

- `reach2` reverse pass, `reach.py` upsert, ECP5 init: #145 items 4-6 unchanged (SQL / graph build).
- Nibble decode is 0.04 s of the 0.073 s plane build; the rest is unpack/sort of keys. Not worth Rust now.
- `Dec.active` warm 0.31 s is memory-bound (51.6 M gathers); further gain needs fewer entries per design (block-level pre-filter).
- Threads for the fast decode: the guard-lease sum for N threaded planes is N x (39 MB bitmap + ~5 MB keys); not used.
