# Cyclone IV GX (EP4CGX150) LAB / M9K / MAC CRAM fields from the vendor asmdb (#169)

Code: `lifters/cycloneiv_clean/fields.py` (+ `asmdb_walk.py`). Tests: `tests/cycloneiv_clean/test_fields.py`.
Scripts: `scripts/cycloneiv_clean_fields_coverage.py` (counts), `scripts/cycloneiv_clean_fields_pairs.py` (pair diffs). Logs: `tmp/logs/cycloneiv_clean_fields_{coverage,pairs}.log`, `tmp/logs/cycloneiv_clean_oracles.log`.
Measured 2026-10-30, Quartus 25.1 EP4CGX150 asmdb, existing corpus only (0 new builds).

## Address rule (vendor-derived, no constant)

- Group bit = signed offset from the instance cell: `abs = hi * 6154 + lo + offset` (sof bit index, A4; then A5).
- Instance cell = `hi << 16 | lo` from BLOCK_INFO `m_block_lists[1]`; index = column * 90 + row; hi -70 per row.
  - LAB 9,360 (104 columns), MEAB 720 (8), MAC 360 (4). Row = Y - 1 (LAB sites; M9K 3 of 3 sites).
- Walk fix: BLOCK_INFO list first element restarts at 0 per BLOCK_INFO. The old rule shifted every LAB `lo` by -4 frames (previous block's last first element). With the fix the LUT specimens match with no constant.
- Names: libdb_asmdb arch-group-type table (4,664 names), `reference/ghidra/globals.tsv`.
- `aux` bits = bits of the group's aux / next-selection muxes (shared routing selection); counted separately.
- Shared bits are vendor-declared: 263 of 12,011 distinct bits in one instance of each type belong to two groups (e.g. LE_USE_SYNC_CLEAR / LE_USE_SYNC_LOAD, RAM_MS_DATA_INPUT 18..35 / _B 0..17).

## Enumeration per block type (asmdb_walk, 6,087 groups)

| block type | groups (std / calc / dumb) | group offsets per instance | instances | placed |
|---|---|---|---|---|
| LAB 18 | 37 (0 / 37 / 0) | 1,245 | 9,360 | yes |
| MEAB 39 | 147 (0 / 147 / 0) | 10,483 | 720 | yes |
| MAC 41 | 93 (0 / 93 / 0) | 578 | 360 | yes |
| HIO 5 / VIO 6 | 55 / 53 | std / dumb: absolute addresses (CRAM tag 0, CFF tag 0xA), see hardblocks doc | 131 / 325 | absolute |
| DEDICATED_CLOCK 60 / NEG 61 | 2 / 2 | 50 / 50 | none (lists keys 3..14, base not decoded) | no |
| CONTROL 8, DEVICE 72, FAST_PLL 43, GENERAL_PLL 45, CLKBUF_GCLK 73, OCT_CAL 98, GX_* 64/67/70/216-219, HSSI_PCIE_HIP 226, HSSI_STRIP 227 | 24, 13, 102, 101, 126, 15, 4/85/17/194/204/168/56, 974, 3,840 | std / dumb: absolute addresses, no instance list | none (HSSI_STRIP key 3 = CFF base) | absolute, see hardblocks doc |

- 605 default objects (597 mux settings + 8 bit-calc); default-bit list 2,518 = 2,319 CRAM + 104 CFF + 95 option (walk now keeps it; matches docs/cycloneiv-address-spaces.md).

## Claimed bits (absolute, distinct)

| block | path bits | aux bits | claimed | already in asm.ddb | new vs asm.ddb |
|---|---|---|---|---|---|
| LAB | 11,138,400 | 93,600 | 11,213,280 | 37,440 | 11,175,840 |
| MEAB | 7,374,960 | 11,520 | 7,385,760 | 5,040 | 7,380,720 |
| MAC | 208,080 | 5,760 | 210,960 | 2,520 | 208,440 |

- Union with asm.ddb (7,620,908) + default list (15 new): 26,385,923 claimed, 12,655,053 unclaimed of 39,040,976 (was 29,023,893 unclaimed, 74.34 %; now 32.4 %).
- Largest LAB roles (bits): LUT INIT 2,396,160; LE input mux (LE_LUT_INPUT) 6,589,440; LAB input mux 411,840; register output 449,280; register clock / clear 149,760 each; register sync 149,760; register mode 299,520; carry 149,760; LAB clock 149,760, clear 93,600, CE 37,440, sync 46,800, invert 74,880.
- Largest MEAB roles: RAM content 6,635,520 (9,216 per M9K); port input mux 639,360; mode 23,760; clear 17,280; CE 12,960; clock 12,960; WE 12,960; RE 12,960; clock/clear select 5,760; output register 1,440.
- MAC roles: input mux 185,040; mode 23,040.
- Remaining unclaimed 12.66 M: no asmdb group places them (IO CRAM offsets, clock, PLL, GX and HSSI blocks have no decoded instance base; the rest lies in column frames no group names). Not shown to be reserved.

## Coverage table

| block type | CRAM bits claimed by vendor group | validated by oracle | matched / missing / extra / wrong |
|---|---|---|---|
| LAB LUT INIT (LE_LUT_FUNCTION) | 2,396,160 | 1,023 specimen sites (16,368 cells), exact set per site, no constant | 16,368 / 0 / 0 / 0 |
| LAB register control (LE_CLEAR_SELECT, LE_USE_SYNC_CLEAR / LOAD, LE_CLOCK_SELECT, LAB_* fast muxes, LE_REG_OUT) | 1,600,560 (register + LAB control roles) | 40 pair diffs (8 LE positions x aclr / ena / sclr / sload / clkKB, FF_X10_Y10) | 416 diff cells: 336 in LAB groups + 80 asm.ddb routing / 0 missing; 0 extra / 0 wrong not scoreable for pairs |
| LAB local-line / PIA muxes, carry, other LE | rest of 11,213,280 | claimed by group; touched by the control pairs (routing changes), not pair-isolated | unvalidated individually |
| MEAB RAM content | 6,635,520 | 46 single-bit init pairs (b16 k*, h* word/bit), unique instance, 1 cell each | 46 / 0 / 0 / 0 |
| MEAB mode / register / clock-enable | 100,080 | 18 clean mode pairs (diff <= 64 cells) | 41 cells / 0 missing |
| MEAB port input muxes | 639,360 | not isolated by an existing pair | unvalidated |
| MAC | 210,960 | no MAC specimen in corpus (0 cycloneiv_mac_mult cells) | unvalidated |
| HIO / VIO / clock / PLL / GX / HSSI | 0 (no base) | n/a | n/a |

## Field labels confirmed by pair diff (existing builds, one feature each)

- LAB (X10_Y10, LE position p = 0..7, 8 of 8 positions identical pattern):
  - `aclr` -> LE_CLEAR_SELECT site p, LAB_CLEAR_FAST_MUX, LAB_CLR_INVERT_PAIR, LE_REG_OUT_YGR#2 site 12.
  - `sclr` -> LE_USE_SYNC_CLEAR site p and LE_USE_SYNC_LOAD site p (one shared bit), LAB_ENABLE_SYNC_SIGNALS.
  - `ena` -> LAB_CE_FAST_MUX#0, LAB_ENABLE_CE#0, LAB_INVERT#1, LE_REG_OUT_YGR#1 site 13.
  - `sload` (+ asdata) -> LE_CLOCK_SELECT site p, LE_USE_SYNC_CLEAR / LOAD site p, LAB_CLOCK_FAST_MUX, LAB_INVERT #0 / #2 / #4, LE_REG_OUT_YGR#1 site 10.
  - `clkKB` (clock net KA to KB) -> LAB_CLOCK_FAST_MUX#0, LAB_SYNC_LOAD_FAST_MUX_MAG, LE_REG_OUT_YGR#2 sites 14, 15.
  - Fields that are LE-specific move with p; the LAB-level ones do not.
- M9K (instances X7_Y60 = col 0 row 59, X23_Y40 = col 1 row 39, X65_Y40 = col 4 row 39; each pair resolves to a unique instance with row = Y - 1; column rank ascending in X):
  - output register on port A / B -> RAM_REG_DATA_OUT / _B, RAM_SELECT_CLK_DATA_OUT / _B, RAM_CE_SELECT_OUTPUT (3 cells).
  - read-during-write old data -> RAM_NEW_DATA_MODE (1 cell); `cke_in_none`, `cke_core_none`, `wrclk` -> RAM_REG_DATA_OUT + RAM_SELECT_CLK_DATA_OUT (2 cells).
  - one MIF bit -> exactly 1 RAM_CONTENT cell, 46 / 46.
- Pairs with ~1,000 diff cells (rom, addrclr, cke_*_ena0, dual port ...) re-route in the fitter; excluded from the table (not one feature). Their non-claimed cells are routing outside the M9K instance, not scored.

## Open

- Value to bit pattern (arch values per selection) for each group not decoded: `Field.values` holds the raw arch values only.
- Bases for HIO / VIO CRAM bits, clock, PLL, GX, HSSI: BLOCK_INFO lists keys 2..14 not yet interpreted.
- No MAC, PLL, or carry-chain specimen in the corpus; RAM port input muxes and LE input muxes unvalidated by pair.
- Sampling-plan builds (4 corners + seeded centre) not started: nothing required a new build to confirm the fields above.
- PLL (CFF absolute), M9K content map, MAC / M9K control signatures: docs/cycloneiv-clean-hardblocks.md.
