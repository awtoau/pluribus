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

## IV asmdb layout (2026-10-30, static decompile of libdb_asmdb `ASMDB_DIE` / `ASMDB_BLOCK_INFO` / `ASMDB_ARCH_GROUP_*::operator<<`)

- Cyclone V reader (`block_infos`) finds 0 records on IV: IV asmdb is the binary PDB stream (no `a : b : c` space strings, names stripped), same layer as routing.ddb (docs/cycloneiv-ddb-format.md).
- Main stream, walked by `io.asmdb_main_stream` (ends at body offset 38,044 of 5,350,270; rest is deferred per-class object pools):
  - 8 block types in `m_block_info_map` (keys 5, 6, 18, 39, 41, 60, 61, 227).
  - `m_arch_group_list` 6,087 pointers: classes 5 / 6 / 7 / 8 = 277 / 4,893 / 913 / 4 (class id = tag >> 2; ids from the stream, class names not yet bound).
  - `m_default_group_list` 580 (classes 10 / 11 = 572 / 8); `m_default_bit_list` 2,518 addresses: CRAM 2,319, CFF 104, OPTION 95; `m_forced_bit_list` 35; `m_labeled_simple_mux_list` 4; local default / arch groups 25 / 225; `m_hc_*` 0.
- Group object fields (pool content): `ARCH_GROUP_BASE` = `m_group_index`, `m_type`, `m_group_block_type`; `STD` / `CALC` add `m_mux_path_list`, `m_mux_data_list` (`MUX_DATA` = arch_value, aux_mux, next_mux_selection); `DUMB` adds `m_arch_value`, `m_bits`; `ASMDB_MUX` = `m_mux_bits`; `BLOCK_INFO` = 3 strings, `m_block_lists`, `m_block_type`, `m_num_ram_cols`, `m_simple_block_lists`, `m_export_port_to_bit_map`, `m_block_bit_to_avalon_bit_map`, `m_avalon_name_to_size_map`.
- Pool order / class-id -> class binding not yet resolved: first pool (body 0x949c) is 16-element offset vectors; the one `m_export_port_to_bit_map` entry (LE block) sits at 0x9b8a0. CFF instance bases per IO site: 0 decoded.

## Pad -> package pin (partial, 0 pins decided)

- `ddb_stingray4fbga896_pkg.ddb`: 896 pin records, ball names in a length-prefixed run, then one record per pin (name, function string such as supply name / DQ role, numeric fields). IO balls have an empty function string (342).
- `ddb_stingray4_pad.ddb`: 520 pad records; each carries `X<x>Y<y>SUB_LOC<n>` (= IOBUF site x, y, n), a pad class string, a function name.
- Pin record carries no field equal to the pad index; ball index minus pad ordinal drifts 25 -> 31 over the oracle balls (96 joined, oracle `build.pin` x `postfit.vo`). The link is not an ordinal and not yet found (needs the DEV_PIN / DEV_PAD serializers).

## Drive / slew / pull

- Not reached: `process_atom` paths for drive strength and slew have not been located; only the pin-mode and standard-class paths are decompiled.

## Class binding and pool formats (2026-10-30)

- Pointer tag class id = tag >> 2 = row of the `.ddb` trailer type table (`io.ddb_types`): asmdb 1 DIE, 2 BLOCK_INFO (8), 5 ARCH_GROUP_CALC (277), 6 STD (4,996), 7 DUMB (1,032), 8 STLMAP (7), 10 DEFAULT_MUX_SETTING (597), 11 DEFAULT_BIT_CALC (8), 13 LABELED_SIMPLE_MUX (4), 14..24 mux classes; main stream references 277 / 4,893 / 913 / 4 of them (the rest are in local lists).
- `vector<unsigned>` on disk: u32 count, then `count` i32 deltas (running sum, first delta against the previous vector of that field). Body offset 38,044 = a 149,760-element vector of repeating 0..15 (LE bit offsets), ends at 0x9b8a0, followed by the BLOCK_INFO `m_export_port_to_bit_map` entry (`le_comb_abs_to_loc` -> 149,760).
- `map<DATA_TYPE, vector<uint>*>`: u32 count, per entry i32 key + pointer tag; contents deferred. Pool interleaving of BLOCK_INFO objects and their vectors is not resolved: CFF instance vectors still undecoded.
- DEV_PIN (libddb_dev `operator<<`, static decompile): `m_id` i32 delta, bool vector (2 delta words), 25 i32 deltas (`m_int_data`), 5 strings (`m_string_data`: [0] ball name, [1] function), 7 delta vectors (`m_vec_int_data`), string-hash (count), 5 bool vectors, `m_pad_id_list` (count + deltas). Pool records of the pkg body are not homogeneous (a second, shorter record kind with 11 ints follows each pin); `m_pad_id_list` not yet read: 0 pins decided.

## Ghidra pass (2026-10-30, #168; workflow: docs/ghidra-workflow.md)

- Pool order: libdb_pdb `PDB_SEGMENT_READER::xfr_ptr` / `finish_reading_all`.
  - Tag u32: 0 null; bit0 = u16 adjust + u16 class idx follow; bit1 = back-reference (id delta); else new object of class `tag >> 2`.
  - New objects append to the declared pointer type's list; pending types sit on a LIFO stack; the popped type's objects are read in creation order, nested new types are handled before earlier ones.
  - Dirt ddb (`scripts/cycloneiv_clean_dirt.py`): one global FIFO of tags reproduces 11/11 dirt files byte-exactly (stingray4 1,642 nodes = 532 + 613 + 497 from the type table).
  - asmdb: the pool after the main stream starts with the last-queued static type, ASMDB_LABELED_SIMPLE_MUX (4 objects): the 149,760-element vector is its `m_mux_bits` (LE bit offsets), `le_comb_abs_to_loc` its label.
  - Deltas (`xfr_int_delta`) are against the same field of the previous object in the pool, not a running sum inside one object.
- Enum names read from libdb_asmdb tables (`ASMDB_TRANSLATOR::m_asmdb_*_debug_string_table`):
  - Block types in the IV asmdb: 5 HIO, 6 VIO (the IO blocks), 18 LAB, 39 MEAB, 41 MAC, 60 DEDICATED_CLOCK, 61 DEDICATED_NEGATIVE_CLOCK, 227 HSSI_STRIP.
  - Arch group `m_type` -> name over 4,664 groups: 84 IO_PIN_MODE, 161 IO_SET_DRIVE_STRENGTH_YGR, 165 IO_USE_BUS_HOLD, 178 IO_USE_PULL_UP, 180 IO_USE_SLOW_SLEW, 182 IO_USE_OPEN_DRAIN, 188..190 IO_OCT_*, 229..231 MIO_SET_*SLEW_RATE, 247/248 MIO_SET_PULLDOWN/PULLUP_STRENGTH, 249 MIO_SET_DRIVE_STRENGTH, 254 MIO_SELECT_IOST_DIRT, 305/306 MIO_USE_BUS_HOLD / MIO_USE_PULL_UP, 506 MIO_PIN_MODE.
- Drive / slew / pull `process_atom` paths (libcomp_asm):
  - Pull-up, bus-hold, slow-slew, open-drain = one boolean mux each (`mux_select(group, resolve_io_index_for_block(), bool)`); sources: cut_io_util vtbl +0x88 / +0x78, atom vtbl +0xe58, atom bit 0x16.
  - Drive strength value = dirt tree lookup `IO / IO_SET_DRIVE_STRENGTH_YGR / IO_STANDARD / CURRENT_STRENGTH / VIO_PAD|HIO_PAD / SETTINGS`; the stingray dirt ddb files carry no IO subtree (only 12 MIO arch-group entries), so the table is not in these dirt files.
- pkg ddb: type table is DEV_PKG_INFO_BODY (1), DEV_PIN (896), std::string: no second record kind; the root holds vector<DEV_PIN*> then hash<string, DEV_PKG_NET*>. The 11-int run is part of the DEV_PIN field stream (not decoded). `ASM_IO_PIN_MODEL_YGR` takes (CDB_CHIP_DB_ENTRY, DEV_DIE_INFO, DEV_PAD_INFO): pad data comes from the pad ddb.
- Still open: group objects (classes 5..8) and mux pools are not walked, so group -> CFF bit vectors and instance bases remain 0; IO fields 0/5.

## asmdb full walk and IO CFF fields (2026-10-30, #168; code: `lifters/cycloneiv_clean/asmdb_walk.py`, test `tests/cycloneiv_clean/test_asmdb_walk.py`)

- The walk consumes the asmdb body exactly (5,350,270 bytes) and every class count equals the ddb type table (277 / 4,996 / 1,032 / 7 groups, 37,564 muxes in 9 classes, 605 default settings, 4 labeled muxes, 7 index maps, 8 block infos).
  - Formats added to the pool rule: vector<uint> first element is a delta against the previous vector's first element; arch-group `m_mux_path_list` = vector<vector<MUX*>> (one path per site), `m_mux_data_list` inline (byte, 2 tags); `xfr_stl_ptr` = presence byte then the container inline; BLOCK_INFO `m_simple_block_lists` = map<int, uint>.
- IO blocks: type 5 HIO = 131 sites, type 6 VIO = 325 sites (BLOCK_INFO list length); each site has one CFF-tagged address set per group, absolute (no instance base needed: DUMB groups carry one bit per site, STD groups one mux per site).
  - HIO site 0 CFF block `0x2d11..0x2d2f` (31 bits; VIO 37): TERMINATION_CONTROL_SELECT 1, SET_SLEW_RATE 2, OUTPUT_DUTY_CYCLE 2, SELECT_IOST_DIRT 3, PIN_MODE 1 (+ CRAM bit), USE_BUS_HOLD 1, USE_PULL_UP 1, USE_PCI_DIODE_CLAMP 1, SET_PULLUP_STRENGTH 8, SET_PULLDOWN_STRENGTH 9 (names = asmdb group types MIO_*).
  - Site stride between neighbouring HIO sites: 38 CFF bits (first element delta).
- Oracle check (150 corpus designs, sites used >= 8): the signature bits of every placed IOOBUF lie in SET_PULLUP_STRENGTH (4) + SET_PULLDOWN_STRENGTH (4, or 3 on 2 sites) + SET_SLEW_RATE (1) of one unique site: 158 / 158 placed; every IOIBUF signature bit (223 / 223 placed) is that site's USE_PCI_DIODE_CLAMP bit. 381 of 388 signature sites place uniquely; 5 IOIBUF sites and 2 empty signatures are unplaced.
- So drive strength = the pull-up / pull-down strength muxes (MIO_SET_PULLUP_STRENGTH, MIO_SET_PULLDOWN_STRENGTH), not a separate group; slew = MIO_SET_SLEW_RATE; pull = MIO_USE_PULL_UP; direction = MIO_PIN_MODE; standard = MIO_SELECT_IOST_DIRT (3 CFF bits).
- Site order: sites run along an edge (HIO: X=117 column by increasing Y, two to four sub-locations per Y; VIO: Y=91 row by decreasing X). A constant offset from the pad-ddb order does not hold (offsets 0 and -4 seen): some pads are not IO sites, so pad -> pin still needs the DEV_PAD type flags.
- Not decoded: value -> bit pattern of each mux (needs the mux data / arch values), site index -> pad -> pin, DEV_PIN field stream (QTL_BOOL_VECTOR).
