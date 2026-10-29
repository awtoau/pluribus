# Cyclone IV GX (EP4CGX150) IO configuration, clean pipeline (2026-10-30, #165)

Code: `lifters/cycloneiv_clean/io.py`. Tests: `tests/cycloneiv_clean/test_io_cff.py` (numbers also in `tmp/logs/cycloneiv_clean_oracles.log`).
Table script: `scripts/cycloneiv_clean_cff_tables.py` -> `databases/cycloneiv/cff2rbf.npz` (local).

## Answer

- IV has a separate programming block for peripheral config: the CFF region. It is not PRAM by name, but the same shape as Cyclone V PRAM.
- IO pin config (the IOE settings) is CFF, not ordinary asm.ddb CRAM. The routing to/from IO pads (IO_DATAIN etc.) is CRAM.
- Status: where the bits are is decoded. Field offsets within an IO site's CFF block are now exact from pair builds (see "Pair builds"); site -> block base is NOT decoded.

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

## Pad -> IO site -> package pin (2026-10-30, #168; code `lifters/cycloneiv_clean/pkgpad.py`, test `test_pkgpad.py`)

- pkg ddb = DEV_PKG_INFO_BODY root (23-bit bool data, 20 ints, 12 strings, 11 vector<vector<int>>, 5 vector<double>) followed by 896 DEV_PIN objects; the run start is found by exact consumption (all 896 parse, body ends at the last byte). The earlier "second record kind with 11 ints" is the root's 11 `m_2d_int_data` vectors.
- pad ddb = 520 DEV_PAD_BODY objects the same way (exact consumption). `QTL_BOOL_VECTOR` = u32 nbits + ceil(nbits/32) i32 deltas.
- Pad classes (strs[3]): Column I/O 324, Row I/O 131, Dedicated Transceiver 32, Dedicated Clock 20, Dedicated Programming 8, JTAG 4, UDCLK 1; strs[1] = site `X<x>Y<y>SUB_LOC<n>`; pad ids are 1..520 in pad order.
- Pin -> pad: 520 of 896 pins carry one pad id; raw `m_pad_id_list` deltas are 0, 1, 2, ... so the k-th pad-bearing pin links pad k. Oracle (postfit.vo `Location: PIN_` x IOBUF site): 400 / 400 balls land on the pad whose site string equals the placed IOBUF (matched 400, wrong 0, missing 0).
- IO site -> pad: HIO sites (block type 5) = the 131 Row I/O pads in pad order, VIO sites (type 6) = the Column I/O pads in pad order; 381 / 381 sites placed by the CFF signatures agree (0 wrong). The earlier 0 / 4 offset came from sorting by geometry; the pad order itself is the site order. VIO has 325 sites for 324 Column I/O pads, so one VIO site has no pad (not assigned).
- Chain ball -> pad -> site -> CFF field bits: 455 IO pins carry a site; 392 of the 400 oracle balls reach the field table (the other 8 are not Row / Column I/O pads).

## Pair builds (2026-10-30, #168 option c): exact CFF labels per IO setting

- Script `scripts/cycloneiv_clean_io_pairs.py` (black box: quartus_map/fit/asm/cpf); tests `tests/cycloneiv_clean/test_io_pairs.py`; local table `databases/cycloneiv/io_pairs.json` (read via `io.io_pairs()`); log `tmp/logs/cycloneiv_clean_io_pairs.log`.
- Method: per sampled site, a 5-port design (pin under test `p`; aux pins `a c e y` in a fixed other bank, identical in every build). Pair = base build + the same build with ONE QSF instance assignment on `p` (value replaced or added). Every build names `IO_STANDARD "2.5 V"` (a drive / slew assignment alone is a fitter error).
- Direction cannot be an assignment: direction pairs differ in the Verilog of `p` only (in / out / tri-state / bidir), assignments identical.
- Diffs: sof tag 21 (CFF bit index = sof bit index), tag 18 (option register), tag 17 (CRAM, counted); rbf frames 0..36 cross-checked through `io.Cff`.
- Sampling (recovery-process.md): per IO bank the 2 farthest-apart pins + 2 seeded interior pins (seed 168), 6 banks (3..8) = 24 sites; sides: bottom (banks 3, 4), right (5, 6), top (7, 8); no user IO bank on the left. Sites come from the corpus pin table (463 pins with a known IOBUF site).
- Builds: 1,200 planned (50 per site); 1,020 built, 180 refused by the fitter (recorded, not retried): 168 output / bidir builds on the 4 input-only sample pins, 4 `1.2 V` on bank 3, 4 weak pull-up and 4 bus-hold on input-only pins. Step times worst of the pilot: map 20.8 s, fit 24.9 s, asm 9.9 s, cpf 2.6 s (12 jobs).

### Results (sites built / tried; pattern = offsets from the site anchor below)

- sampled sites 24 (per bank: 2 ends + 2 seeded interior), output-capable 20, input-only 4 (fitter refuses every output / bidir build there)
- pair rows: 972 built, 180 refused or absent; sof-vs-rbf: every sof CFF diff bit also in the rbf diff in 955 / 972 rows

| setting | value | base kind | sites built / tried | CFF bits per site | sites with the modal pattern | option bits | CRAM cells (min..max) |
|---|---|---|---|---|---|---|---|
| bus-hold | ON | bidir | 20 / 24 | 1 | 20 / 20 | 0 | 0..0 |
| bus-hold | ON | in | 20 / 24 | 1 | 20 / 20 | 0 | 0..0 |
| bus-hold | ON | out | 20 / 24 | 1 | 20 / 20 | 0 | 0..0 |
| direction | in->bidir | in | 20 / 24 | 9 | 20 / 20 | 0 | 68..212 |
| direction | in->out | in | 20 / 24 | 10 | 20 / 20 | 0 | 88..182 |
| direction | in->tri | in | 20 / 24 | 9 | 20 / 20 | 0 | 79..191 |
| direction | out->tri | out | 20 / 24 | 1 | 20 / 20 | 0 | 53..238 |
| direction | tri->bidir | tri | 20 / 24 | 0 | 20 / 20 | 0 | 26..201 |
| drive | 16MA | bidir | 20 / 24 | 6 | 20 / 20 | 0 | 0..0 |
| drive | 4MA | bidir | 20 / 24 | 5 | 20 / 20 | 0 | 0..0 |
| drive | 12MA | out | 20 / 24 | 7 | 20 / 20 | 0 | 0..0 |
| drive | 16MA | out | 20 / 24 | 6 | 20 / 20 | 0 | 0..0 |
| drive | 4MA | out | 20 / 24 | 5 | 20 / 20 | 0 | 0..0 |
| drive | 8MA | out | 20 / 24 | 7 | 20 / 20 | 0 | 0..0 |
| drive | MAXIMUM CURRENT | out | 20 / 24 | 6 | 20 / 20 | 0 | 0..0 |
| drive | MINIMUM CURRENT | out | 20 / 24 | 5 | 20 / 20 | 0 | 0..0 |
| open-drain | ON | bidir | 20 / 24 | 0 | 20 / 20 | 0 | 0..0 |
| open-drain | ON | out | 20 / 24 | 0 | 20 / 20 | 0 | 0..0 |
| open-drain | ON | regoe | 20 / 24 | 0 | 20 / 20 | 0 | 0..0 |
| open-drain | ON | tri | 20 / 24 | 0 | 20 / 20 | 0 | 0..0 |
| pull-up | ON | bidir | 20 / 24 | 1 | 20 / 20 | 0 | 0..0 |
| pull-up | ON | in | 20 / 24 | 1 | 20 / 20 | 0 | 0..0 |
| pull-up | ON | out | 20 / 24 | 1 | 20 / 20 | 0 | 0..0 |
| registered-input | ON | regin | 24 / 24 | 0 | 20 / 20 | 0 | 0..140 |
| registered-oe | ON | regoe | 20 / 24 | 0 | 20 / 20 | 0 | 120..186 |
| registered-output | ON | regout | 20 / 24 | 0 | 20 / 20 | 0 | 135..262 |
| slew | 0 | bidir | 20 / 24 | 1 | 20 / 20 | 0 | 0..0 |
| slew | 0 | out | 20 / 24 | 1 | 20 / 20 | 0 | 0..0 |
| slew | 1 | out | 20 / 24 | 2 | 20 / 20 | 0 | 0..0 |
| slew | 2 | out | 20 / 24 | 0 | 20 / 20 | 0 | 0..0 |
| standard | 3.3-V LVTTL | bidir | 20 / 24 | 8..16 | 16 / 20 | 0 | 0..0 |
| standard | 1.8 V | in | 24 / 24 | 2..12 | 16 / 20 | 0 | 0..0 |
| standard | 3.3-V LVTTL | in | 24 / 24 | 0..8 | 16 / 20 | 0 | 0..0 |
| standard | SSTL-2 Class I | in | 24 / 24 | 4 | 2 / 20 | 0 | 0..0 |
| standard | 1.2 V | out | 16 / 24 | 9 | 16 / 16 | 0 | 0..0 |
| standard | 1.5 V | out | 20 / 24 | 9..21 | 16 / 20 | 0 | 0..0 |
| standard | 1.5-V HSTL Class I | out | 20 / 24 | 9..21 | 16 / 20 | 0 | 0..0 |
| standard | 1.8 V | out | 20 / 24 | 4..14 | 16 / 20 | 0 | 0..0 |
| standard | 1.8-V HSTL Class I | out | 20 / 24 | 4..14 | 16 / 20 | 0 | 0..0 |
| standard | 3.0-V LVCMOS | out | 20 / 24 | 7..14 | 16 / 20 | 0 | 0..0 |
| standard | 3.0-V LVTTL | out | 20 / 24 | 7..14 | 16 / 20 | 0 | 0..0 |
| standard | 3.0-V PCI | out | 20 / 24 | 8..15 | 16 / 20 | 0 | 0..0 |
| standard | 3.3-V LVCMOS | out | 20 / 24 | 5..13 | 16 / 20 | 0 | 0..0 |
| standard | 3.3-V LVTTL | out | 20 / 24 | 8..16 | 16 / 20 | 0 | 0..0 |
| standard | SSTL-18 Class I | out | 20 / 24 | 4..14 | 16 / 20 | 0 | 0..0 |
| standard | SSTL-2 Class I | out | 20 / 24 | 0 | 20 / 20 | 0 | 0..0 |
| termination | SERIES 25 OHM WITHOUT CALIBRATION | out | 20 / 24 | 7 | 20 / 20 | 0 | 0..0 |
| termination | SERIES 50 OHM WITHOUT CALIBRATION | out | 20 / 24 | 0 | 20 / 20 | 0 | 0..0 |

Modal CFF bit offsets from the site anchor (min bit of the site's location signature), per setting:

- bus-hold ON (bidir): [10]
- bus-hold ON (in): [10]
- bus-hold ON (out): [10]
- direction in->bidir (in): [0, 15, 18, 19, 20, 24, 27, 28, 29]
- direction in->out (in): [0, 12, 15, 18, 19, 20, 24, 27, 28, 29]
- direction in->tri (in): [0, 15, 18, 19, 20, 24, 27, 28, 29]
- direction out->tri (out): [12]
- drive 16MA (bidir): [14, 15, 16, 25, 26, 27]
- drive 4MA (bidir): [15, 16, 19, 24, 26]
- drive 12MA (out): [14, 15, 18, 19, 26, 28, 29]
- drive 16MA (out): [14, 15, 16, 25, 26, 27]
- drive 4MA (out): [15, 16, 19, 24, 26]
- drive 8MA (out): [17, 18, 20, 24, 25, 26, 28]
- drive MAXIMUM CURRENT (out): [14, 15, 16, 25, 26, 27]
- drive MINIMUM CURRENT (out): [15, 16, 19, 24, 26]
- pull-up ON (bidir): [11]
- pull-up ON (in): [11]
- pull-up ON (out): [11]
- slew 0 (bidir): [0]
- slew 0 (out): [0]
- slew 1 (out): [0, 1]
- standard 3.3-V LVTTL (bidir): [15, 16, 19, 20, 21, 24, 26, 29]
- standard 1.8 V (in): [8, 12]
- standard SSTL-2 Class I (in): [-468, 5, 9, 12]
- standard 1.2 V (out): [8, 14, 18, 23, 24, 25, 26, 28, 29]
- standard 1.5 V (out): [8, 14, 15, 20, 23, 24, 27, 28, 29]
- standard 1.5-V HSTL Class I (out): [8, 14, 15, 20, 23, 24, 27, 28, 29]
- standard 1.8 V (out): [8, 16, 25, 27]
- standard 1.8-V HSTL Class I (out): [8, 16, 25, 27]
- standard 3.0-V LVCMOS (out): [18, 21, 24, 25, 26, 27, 28]
- standard 3.0-V LVTTL (out): [18, 21, 24, 25, 26, 27, 28]
- standard 3.0-V PCI (out): [12, 16, 17, 20, 21, 23, 28, 29]
- standard 3.3-V LVCMOS (out): [15, 17, 21, 24, 29]
- standard 3.3-V LVTTL (out): [15, 16, 19, 20, 21, 24, 26, 29]
- standard SSTL-18 Class I (out): [8, 16, 25, 27]
- termination SERIES 25 OHM WITHOUT CALIBRATION (out): [14, 15, 17, 23, 24, 26, 28]

- standards (out kind) with distinct anchored CFF diffs: 8 of 12 tried
  - ['SSTL-2 Class I']: 0 bits
  - ['1.5 V', '1.5-V HSTL Class I']: 9 bits
  - ['1.2 V']: 9 bits
  - ['1.8 V', '1.8-V HSTL Class I', 'SSTL-18 Class I']: 4 bits
  - ['3.0-V PCI']: 8 bits
  - ['3.3-V LVTTL']: 8 bits
  - ['3.3-V LVCMOS']: 5 bits
  - ['3.0-V LVCMOS', '3.0-V LVTTL']: 7 bits

### Findings

- **Site anchor.** Location pairs (`out` base at site S vs the first site of the same aux group) give an 11-bit site signature at all 20 output-capable sites, same shape everywhere: offsets `[0, 8, 9, 15, 18, 19, 20, 24, 27, 28, 29]` from the lowest bit. Every field offset in the table is relative to that bit and identical at all banks 4..8 sites; so each IO field is a fixed offset in a per-site CFF block, and what is missing is only site -> anchor.
- **Anchors run monotonically around the ring**: top (x ascending), right (y descending), bottom (x descending) give strictly increasing anchors 493 .. 17,755 at 20 / 20 sites (the pair-derived anchors are in `io_pairs.json`, `location`). Stride is not constant (pad spacing differs), so no formula is claimed.
- **Fields with CFF bits (all built sites agree, option register 0 bits everywhere):** standard (4..21 bits, 8 distinct diffs among 12 standards), drive (4 mA / min = 5 bits, 8 mA = 7, 12 mA = 7, 16 mA / max = 6), slew (0 = 1 bit, 1 = 2 bits, 2 = base), weak pull-up (1 bit, offset 11), bus-hold (1 bit, offset 10), 25 ohm series termination (7 bits), direction (in -> out 10 bits, in -> tri-state / bidir 9, out -> tri-state 1 bit at offset 12).
- **Settings with NO CFF effect in these builds:** open-drain (all 4 kinds; build bit-identical in CRAM and CFF, so the assignment may not apply to the netlist; unresolved = missing), registered output / OE / input (change CRAM only: 120..262 cells at output-capable sites), 50 ohm series termination, SSTL-2 Class I (same bits as `2.5 V`), tri-state -> bidir (CFF 0, CRAM only).
- Drive: `4MA` = `MINIMUM CURRENT`, `16MA` = `MAXIMUM CURRENT`; explicit `12MA` and `8MA` both differ from the unassigned default (which the pin report prints as "Default"), so default drive of `2.5 V` is neither.
- Bank 3 (4 of 4 sites): the standard field appears twice, own block plus a second 8-bit block at a site-specific offset (offsets -468 .. +2,734 from the anchor); banks 4..8 (16 sites) have one block only. Not chased.
- Double-group bits: sof bits 4521 and 6952 (multiplicity 8 in `cff2rbf`) change in the sof but not in their first rbf group (17 rows); the value of those two sits in the second group. This contradicts the E6 note "only the first group is the value" for IO fields.
- rbf-only cells (bit 3072 in 112 rows, 23,966 / 14,514 / 14,520 / 22,980 in others) change without a sof CFF change: not IO fields (no site relation), listed in `rbf_extra`.

### Against prior expectation (ambiguous = missing)

| Expectation | matched | missing | extra | wrong |
|---|---|---|---|---|
| Corpus IOOBUF 9-bit signature, sites with a corpus oracle (6 of 20 sites, 54 bits) | 54 | 0 | 12 (offsets 8, 9 at every such site) | 0 |
| Direction mux, 7 values (`io.PIN_MODE_MUX`): CFF-distinct states observed | 3 (input, output, output + OE) | 4 (open-drain x2, registered OE x2) | 0 | 0 |
| Standard classes 0..12 (`asm_convert_db_to_asm_iost`): distinct diffs among 12 standards + base | 8 distinct diffs | 5 classes not separated by the standards tried | 0 | 0 |
| IO fields with an exact label (direction, standard, drive, slew, pull-up, bus-hold, termination, open-drain, registered in / out / OE) | 7 | 4 (open-drain, 3 registered) | 0 | 0 |

- Comparison only: the 7-value mux and the class table were not used to choose or interpret builds. Mux value labels (0..6) are not assigned to builds beyond the three distinct states.
- Counts: 11 setting classes + pin location tried; 48 (setting, value, base kind) pair groups, 36 with CFF bits at every built site, 11 with none, 1 mixed (`3.3-V LVTTL` on `in`: input-only sites differ); 972 pair rows built (24 sites), 4,052 CFF bit differences at the 20 output-capable sites.
- Still open: site -> anchor (pad -> pin), open-drain effect, registered-field location in CRAM, bank-3 second block, drive 12 mA vs default.

## Cross-check A x B and decoded value table (2026-10-30, #168; code `lifters/cycloneiv_clean/io_decode.py`, test `tests/cycloneiv_clean/test_io_decode.py`)

- A = asmdb group addresses per site (`asmdb_walk`, `pkgpad`); B = pair-diff bits of the 24 sampled sites (`io.io_pairs()`); absolute bits read from the same builds. Output: `databases/cycloneiv/io_decode.json` (local; `python3 -m lifters.cycloneiv_clean.io_decode`).
- Scope: 20 output-capable sites. The 4 input-only sample pins (A15, AJ16, T29, V29) are dedicated-clock pads: not Row / Column I/O pads, no A site (blocks 60 / 61 not walked) = missing.

### Per-field score (bit level, summed over 20 sites; `cross_check`)

- matched = B diff bits inside the field's A group; missing = A group bits no tried value toggled; extra = B diff bits outside the group; wrong = 0 (every B-only bit is counted extra and classed).

| Field (A group) | matched | missing | extra | extra class |
|---|---|---|---|---|
| slew (SET_SLEW_RATE) | 40 | 0 | 0 | |
| pull-up (USE_PULL_UP) | 20 | 0 | 0 | |
| bus-hold (USE_BUS_HOLD) | 20 | 0 | 0 | |
| drive (SET_PULLUP + PULLDOWN_STRENGTH) | 260 | 80 | 0 | missing = strength bits not toggled by the 6 values tried |
| standard (SELECT_IOST_DIRT) | 60 | 14 | 412 | 320 other groups of the same site (strengths, PCI clamp: defaults follow the standard), 92 IOST bits of another site (below) |
| termination (TERMINATION_CONTROL_SELECT) | 0 | 20 | 140 | 140 strength bits; the select bit never changes |
| direction (PIN_MODE) | 0 | 20 | 200 | 200 = slew / strength / PCI clamp bits; PIN_MODE CFF bit never changes |
| open-drain (PIN_MODE) | 0 | 20 | 0 | assignment builds bit-identical |
| registered in / out / OE | no CFF group in A | | | CRAM only (below) |

- Site -> anchor: anchor = lowest CFF bit of the site's SET_SLEW_RATE group; equals the pair-derived location anchor at 20 / 20 sites. Every field offset = A address - anchor, so no separate anchor table is needed.
- Value patterns (`values`, element i of the group's mux = value bit i): every primary entry has one pattern at every site of its group size (0 disagreeing). Examples: slew 0 / 1 / 2 = `00` / `10` / `01` (default 2); pull-up and bus-hold ON = `1`; drive `4MA` = `MINIMUM CURRENT`, `16MA` = `MAXIMUM CURRENT`, 4 / 8 / 12 / 16 mA each a distinct (pull-up 8 bit, pull-down 9 bit) pair; IOST 2.5 / 3.0 / 3.3 V = `000(0)`, 1.2 / 1.5 / 1.8 V and HSTL / SSTL-18 = `010(0)`, SSTL-2 input = `101(0)`.
- Standards are told apart by IOST plus the strength / clamp groups the standard implies (3.3 V LVTTL and 2.5 V share IOST `000`); the table keeps all groups that differ from the base build.
- Direction: in / out / tri / bidir share PIN_MODE CFF = 0. Input = USE_PCI_DIODE_CLAMP 1 (out: 0), output = slew `01` + non-zero strengths (in: slew `00`).

### B oddities explained

- Foreign standard bits (92): the extra IOST bit of a pin is an IOST bit of the VREF pad of its bank (`VREFB<bank>N<k>`), 20 / 20 sites; bank 3 additionally changes the strength groups of site 2 (`NCEO`, bank 3 config pad) = the "second 8-bit block" (it is the same absolute block for all 4 bank-3 sites, not site-specific). Which VREF pad serves which pin is not decoded from A (pad ddb carries no VREF group id found yet).
- Double-group bits: sof bits 4521 (PULLUP_STRENGTH, 12 rows) and 6952 (USE_PCI_DIODE_CLAMP, 5 rows): first rbf cell group never changes, second group changes in every row. For these bits the value is the second group; the E6 note "first group is the value" holds for the 62 others only where tested (not IO-tested). The rbf-only cells in `rbf_extra` (3072, 14514, 14520, 22980, 23966) are also double-group bits.
- Open-drain: `AUTO_OPEN_DRAIN_PINS` is a detection switch (default ON), not a forced mode; the decompile selects mux 3 / 4 / 6 from atom bit 0x16 (constant-0 tri-state data). New builds (`scripts/cycloneiv_clean_io_od.py`, 3 sites): `p = e ? 1'bz : 1'b0` differs from the plain output only in the MIO_PIN_MODE CFF bit (0 -> 1) at 3 / 3 sites; `od` vs `od` with the assignment OFF is bit-identical. So PIN_MODE CFF = open-drain flag; B's pair table missed it because the pair designs never had constant-0 data.
- Registered fields (CRAM, sof tag 17 index = asm address, little-endian bits; groups hit with the same count at every site; `cram_fields`): input register = INREG_CLK_FAST_MUX 1, USE_CLR_INREG 1; output register = OUTREG_CLK_FAST_MUX 1, REG_FEEDS_PIN_OUT 2, SET_CE_TO_OUTREG_TIE_OFF 1, USE_CLR_OUTREG 1; OE register = OUTREG_CLK_FAST_MUX 1, OEREG_POWERS_UP_HIGH 1, SET_CE_TO_OEREG_TIE_OFF 1, USE_CLR_OEREG 1, PIN_MODE 1 (CRAM bit). Direction and open-drain builds hit no constant IO CRAM group.

### Still open

- VREF pad -> pin map (the foreign IOST bit), IOST value of a 3-element site's shared 4th bit, CRAM value patterns of the registered fields, 50 ohm termination and SSTL-2 output (no CFF change), the 4 dedicated-clock pads.
