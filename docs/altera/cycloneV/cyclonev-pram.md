# Cyclone V PRAM (peripheral RAM) decode

Scope: the cleartext PRAM section of a `.rbf`, any Cyclone V die with tables. CRAM is never read, so encrypted images decode.
Tool: `scripts/cyclonev_pram_decode.py {cff,oracle,images,all}` (+ `scripts/cyclonev_pram_core.py`), log `tmp/logs/cyclonev_pram_decode.log`.
Image-specific output stays in `vendor-analysis/altera/pram/` (gitignored); images are named by label in a local config.

## Geometry (container, validated by frame CRC16 on every file)

- `S` = sync offset (0x80). Option RAM is 32 strips x 40 bits; PRAM follows. `fs` = die `frame_size` (words).
- PRAM frame = `4*fs + 8` bytes (CRC16 in the last 2). First PRAM frame at file offset `pram_frame_bytes + 104`.
- Frame count = `ceil(mpram / fs)`, `mpram = max(pram_sizes)`. 32 strips (chains); `pram_sizes[s]` bits each.
- Bit `i` of strip `s`: `base = mpram - i - 1`; byte `= pram_off + 4 + (s>>3) + 4*base + 8*(base // fs)`; mask `1 << (s&7)`.
- Die 0x05 (5CEBA4): `fs=129`, 64 frames x 524 B, 14 strips, 51,101 bits. Die 0x13 (5CEBA7): `fs=227`, 58 frames x 916 B, 16 strips, 113,922 bits.
- Field positions = `(strip, start) + mux offsets` from the native tables (`scripts/cyclonev_native_tables.py`, Mistral `data/` bootstrap). `cyclonev_pram_core.owners()` lists the claiming field of every PRAM position.
- Tile identity for GPIO needs a package table; the PRAM alone gives tile coordinates and pad index, not ball names.

## Quartus config-field CSVs (`zb8` / `zb16`)

- Parsed to roles and groups (`stage cff`). Prediction P1 (written first) held:
  - IO-cell and LVDS groups: 152 rows = 4 pads x 38 bits, `BIT_SEQ` 0..37 per pad, 252/252 (zb8) and 320/320 (zb16) pads.
  - PLL: 348 rows per group (zb16 4 groups, zb8 2); same field list in every group (offsets relative to group start).
  - `BINDEX` unique per file. CSV rows: zb8 10,361, zb16 13,729 vs PRAM bits 51,101 (die 0x05) / 113,922 (die 0x13): the CSV names a subset (27% / 12%).
- Files are byte-identical in all 7 die directories: not die-specific. Block counts: zb16 has 4 PLL groups = die 0x05's 4 fPLL; die 0x13 has 7 fPLL, so neither file is a per-die map.
- (BROW, BCOL, BINDEX) -> PRAM position is NOT established as a formula:
  - CSV counter fields run 9 bits per lo/hi half, PRAM tables use 8 + separate bypass / odd-duty bits (one per counter, in other offset ranges).
  - CSV counter order is C4..C0 with stride 18; PRAM DPRIO range is C0..C8 with stride 16, opposite direction. No single affine `BINDEX -> offset` exists even inside the counter range; the bridge is per field.
  - The 9th CSV bit of each counter half (bypass vs odd-duty assignment) has no value check.
- Use today: field-name bridge for PLL M / N / counter lo / hi; everything else (IO cells, LVDS) has no name correspondence with the PRAM tables.

## Oracle check: FPLL against Quartus post-fit `.vo`

Corpus `corpus/cyclonev` (die 0x05, 15 builds with one enabled PLL), `defparam`s of `FRACTIONAL_PLL` and `PLL_OUTPUT_COUNTER` vs the raw PRAM field of the enabled FPLL tile (`stage oracle`).

- Prediction P2: every mapped field equals its defparam. Result: 636 / 651 comparisons equal; the 15 misses are all one field (`cp_comp`, 0 / 15: PRAM bit 0, oracle true). Constant in the corpus, so polarity or bit identity of that field is wrong in the table (issue filed).
- Field tiers (computed): V = 5 fields whose value varies across builds and always matched (M hi / lo, output-counter hi / lo / odd-duty); C = 37 matched but constant.
- Position-pinned bits (both 0 and 1 seen, always equal): 14 of 493 compared bit positions. The corpus varies PLL settings little; the claim is "consistent", not "every bit pinned".
- PLL counter formula `fout = fref * M / (N * C)` with `M = hi + lo`, `C = hi + lo` of the used counter (checked on the 75 MHz build: M=12, N=2, C=4).
- Other Quartus evidence for die 0x05 (not re-run here): GPIO `drive_strength` 51 names MATCH, 0 MISMATCH (`docs/altera/cycloneV/cyclonev-blockmux-fuzz-status.md`); pin used / direction / bus_hold / open_drain 100% over 236 designs (`docs/altera/cycloneV/cyclonev-native-decoder.md`).
- Not covered by any Quartus pair on any die: IO-standard variants beyond the fuzzed set, OCT termination names, DLL, DQS16 internals, clock-mux selects (presence only), HMC, HSSI, HIP, PMA3.

## Tiers for decoded images

- G: GPIO drive_strength / bus_hold / open_drain, die 0x05.
- V / C: FPLL fields from the oracle run above, die 0x05.
- T: all other claimed fields, and every field on die 0x13 (same mux tables, tile offsets from the die's `pram.txt`).
- U: set PRAM bit claimed by no mux.
- Origin control (P3): over 7 cleartext images (2 die 0x05, 5 die 0x13) set bits claimed by no field = 0 with the geometry above; with every claim shifted by +1 / +2 / +3 positions: 235-376 (die 0x05) and 657-778 (die 0x13) set bits fall outside all claims. 4,661 (die 0x05) and 13,174 (die 0x13) PRAM positions belong to no field and are 0 in all 7 images.

## Gaps

- No hardware or Quartus pair for die 0x13; PRAM origin and claim fit are CRC- and claim-validated only.
- Default values of GPIO fields depend on the package (bonded pin or not); decode assumes the model's package.
- CRAM-resident parts of the peripheral configuration (PMA3 `c` muxes, inverters, core routing) need CRAM; not read for encrypted images.
- Proposed Quartus set to close the IO gaps (<= 30 builds, one change per pair, same placement, predictions first): drive strength x I/O standard on one pin (~12), OCT series / parallel termination (~6), slew rate and weak pull-up (4), LVDS pair vs single-ended (2), DQS group usage (2), DLL on / off (2). Expected: only the field of the changed setting differs in the PRAM; no run yet.
