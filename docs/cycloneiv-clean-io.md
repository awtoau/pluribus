# Cyclone IV GX (EP4CGX150) IO configuration, clean pipeline (2026-10-30, #165)

Code: `lifters/cycloneiv_clean/io.py`. Tests: `tests/cycloneiv_clean/test_io_cff.py` (numbers also in `tmp/logs/cycloneiv_clean_oracles.log`).
Table script: `scripts/cycloneiv_clean_cff_tables.py` -> `databases/cycloneiv/cff2rbf.npz` (local).

## Answer

- IV has a separate programming block for peripheral config: the CFF region. It is not PRAM by name, but the same shape as Cyclone V PRAM.
- IO pin config (the IOE settings) is CFF, not ordinary asm.ddb CRAM. The routing to/from IO pads (IO_DATAIN etc.) is CRAM.
- Status: where the bits are is decoded. Which bit is direction / standard / drive / slew / pull is NOT decoded (0 fields).

## Evidence

| # | Fact | Source | Count |
|---|---|---|---|
| E1 | The assembler bit address carries a space tag: CRAM (bit 31 clear), CFF (`101` top), UNVM (`1001`), OPTION (`10001`), DPRIO (`100001`), literals (`11`) | static decompile of `ASM_BITFIELD::silent_set_bits` (libcomp_asmcc, 0x117e50); `io.ADDRESS_SPACES` | 5 spaces + literals |
| E2 | The vendor die record counts them separately: CRAM 39,040,976, CFF 31,060, UNVM 0, option register 160 | `ASMDB_DIE::operator<<` field order, asmdb body offsets 5/9/13/17; `io.die_head()` | read live in the test |
| E3 | The sof has one section per space: tag 17 CRAM = 12 + ceil(39,040,976 / 8) = 4,880,134 B; tag 21 CFF = 12 + ceil(31,060 / 8) = 3,895 B; tag 18 option = 40 B | `sfl_ep4cgx150.sof` section walk | 4,880,134 / 3,895 / 40 |
| E4 | asm.ddb holds CRAM only | census of all entries with `io.classify` | 51,565,365 / 51,565,365 CRAM; 0 CFF, 0 UNVM, 0 option; min 3,105, max 39,037,932 < 39,040,976 |
| E5 | CFF bits land in the rbf periphery frames 1..36, never in CRAM frames (37..) | bit-plane sofs through `quartus_cpf` (same method as A5): 15 planes + 15 complements | 31,060 / 31,060 bits seen, 0 unseen, 124,496 cells, frames 1..36 |
| E6 | Each CFF bit is written to 4 consecutive bytes of one lane (30,996 bits); 64 bits have a second group of 4 | same measurement | multiplicity {4: 30,996, 8: 64} |
| E7 | The 4 primary replicas agree in Quartus-built rbf files | 60 corpus rbfs | 7,454,400 / 7,454,400 cells agree, 0 wrong |
| E8 | The sof option section (tag 18, 320 bits) reaches the rbf header frame 0 only | same measurement | 51 cells, 35 distinct bits seen, 285 unseen |

- E6 note: the 64 double-group bits differ in their second group in every build; only the first group is treated as the value.
- E8: option-register layout is not claimed; only that it is frame 0.

## What the CFF region holds (oracle, not a source)

- Oracle = 150 Quartus-built GX150 corpus rbfs with the used IO sites from `postfit.vo`. Rule: CFF bits set in >= 95 % of designs using a site and <= 3 % of the others, sites with >= 8 uses.
- Result (692 sites used, 388 with >= 8 uses):
  - IOIBUF: 228 sites carry exactly 1 CFF bit, 2 carry 0 (missing).
  - IOOBUF: 156 sites carry the same 9-bit shape (offsets 0,15,18,19,20,24,27,28,29), 2 carry 8 of them (1 missing each).
- The earlier "36-bit / 4-bit signature in clusters of 4 consecutive v" of the periphery notes is this: 9 and 1 CFF bits times the 4 replicas.
- Every corpus pin is 2.5 V with default drive / slew / pull (build.pin: 3,325 input + 2,274 output rows, one standard). The signature is therefore enable + default state only; direction, standard, drive, slew and pull are not separable from this corpus.

## Accepted inputs used

- asmdb die head (E2), `silent_set_bits` tags (E1), sof sections (E3), asm.ddb (E4), `quartus_cpf` as a black box (E5).
- Banned inputs: none used (no AFX, no learned maps, no constant fitted to one cell). The signature rule above is a validation oracle only.

## Derivation steps still to do

- Group the asmdb arch groups by block type; find the IO block types and their per-instance base vectors (CRAM instances were found as `(hi << 16) | lo` cells; CFF instances need the tag arithmetic of E1).
  - Observed, not decoded: asmdb body 0x278f8e holds a run of 24,003 vectors / 564,065 elements, 497,270 of them in the `0x5` top-nibble family and 66,769 in `0x6` after the pool's delta accumulation; the accumulation start is not established, so tags are unproven.
  - Shape search: the 9-bit OBUF shape was searched as a window of 9 in 114,117 pool vectors: 0 hits. The 9 bits therefore come from several muxes / groups.
- Group index -> setting name: asmdb groups are unnamed. Names live in the callers (`ASM_IO_PIN_MODEL_YGR::process_atom`, `ASM_IO_SET_DRIVE_STRENGTH_YGR`, `ASM_IOST_CZAR_YGR` in libcomp_asm). Needs decompile of those and their enum constants.
- Pad -> pin: `ddb_stingray4_pad.ddb` (520 `DEV_PAD`, 89 `DEV_IO_STANDARD_DESC`, 32 `DEV_IO_RULE`) and `ddb_stingray4fbga896_pkg.ddb` (896 `DEV_PIN`) are the sources. Pad bodies are `QTL_BOOL_VECTOR` / int / string tables keyed by `DEV_PAD_*_ENUM`; enum names not recovered. Oracle for the result: `build.pin` (ball, direction, standard) joined to `postfit.vo` sites by signal name.
- Specimens needed before any field claim: one pin, one setting changed per pair (standard, drive, slew, pull, direction, bus hold). The corpus has none.

## Direction mux (2026-10-30, static decompile of `ASM_IO_PIN_MODE::process_atom`, libcomp_asm 0x29101c)

- The pin-mode setting is one arch-group mux with 7 values (`io.PIN_MODE_MUX`): 0 input, 1 output (OE const), 2 output + OE, 3 open-drain, 4 open-drain + OE, 5 registered OE, 6 registered-OE open-drain.
- Selected via `ASM_ARCH_GROUP::mux_select(this, resolve_io_index_for_block(), value)`; the group index comes from `ASM_IO_PIN_MODEL::construct_gid_to_pin_index_map` (dirt index cache 0x17).
- I/O standard is a separate mux (`handle_ygr_dual_pin_iost`: 0/1 select by standard class 0x37.. / 0x47.. / 0x48.. + atom bit 4); `asm_convert_db_to_asm_iost` maps DEV_IO_STANDARD_ENUM to class 0..12 (not yet tied to a group).
- Corpus fit: IOIBUF = value 0 (1 CFF bit), IOOBUF = value 1 (9 bits); consistent, not yet bit-exact.
- Not done: asmdb block/group walk for the IV die. The Cyclone V `block_infos` reader finds 0 CFF block records in the IV asmdb body (record layout differs); group -> CFF vectors, instance bases, pad -> pin, field decode all still 0.
- Decompile outputs: gitignored `vendor-analysis/altera/analysis/io/`.
