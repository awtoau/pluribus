# Cyclone IV GX `.ddb` (Quartus device database) format

Source: `quartus-25.1/quartus/common/devinfo/cycloneivgx/ddb_stingray4_*.ddb` (STINGRAY4 = EP4CGX150, same files serve EP4CGX110; own licensed install, analysed for interoperability, never redistributed or committed).
Readers: `scripts/cyclonev_ddb_decode.py` (container, shared with Cyclone V), `scripts/cycloneiv_ddb_asm.py` (asm records), `scripts/cycloneiv_asm_decode.py` + `scripts/cycloneiv_asm_tables.py` (decode + oracle scoring).
Measured 2026-10-26. Cyclone V sibling: [cyclonev-ddb-format.md](cyclonev-ddb-format.md).

## Container

- Identical to Cyclone V: 0x73-byte header, zlib body (sync-flushed, cut at `body_end`), zlib trailer = type table. `cyclonev_ddb_decode.py check` passes on asm / routing / icname (0 errors).
- Type tables (same `DYGR_*` classes and layout crcs as Cyclone V):
  - asm: `DYGR_ROUTE_ASM_NODE` 1,802,443; `unsigned short` 17,063,471; `DYGR_ROUTE_ASM_BIT` 51,565,365 (sizeof 5 = i32 + i8 in memory).
  - routing: 30 types (`DYGR_ROUTE_ELEMENT_TEMPLATE` 197,688; `int` / `unsigned short` 3,612,712 each; `DYGR_LOOKUP<...>` nests). Body header `u32 4, 118, 92, 1802443` = version, columns (X 0..117), rows (Y 0..91), nodes. Not decoded further.
  - icname: `DYGR_ROUTE_ICNAME_INFO_BODY`, strings.

## asm body (`cycloneiv_ddb_asm.py parse`)

- Header `u32 4, u32 N, u32 N` (12 bytes), then N records; parse ends exactly at EOF, sums equal the type-table counts.
- Record = `i32 lead, u16 n, n x u16 vals, u16 nb, nb x (i32 delta, i32 flag)`.
  - `lead` = `(i16 dn, i16 dnb)`: this record's `(n, nb)` minus the previous record's. Pure delta coding, no semantics.
  - The Cyclone V reader's framing (`u16 max_n, u16 max_nb` in the header, per-record i32 *trailer*, "< 8-byte stub" at the end) is this same stream shifted by 4 bytes; both parse to the same bits.
- Position = running sum of `delta` over ALL records (empty records add nothing) = `frame + 6154 * v` in a CRAM address space of 6154 frames x 6344 rows (8 bit-lanes x 793 bytes); max 39,037,932, no wrap. 7,620,908 distinct positions.
- Groups: `vals[0]` is a flag (1 on 7,963 records); `vals[1:]` = sizes of the first n-1 fanout groups, the last group's size is implicit (`nb - sum`). Sizes: 3 (14.1 M), 2 (1.4 M), 4 (713 k), 6 (345 k), 1 (232 k), 12 (68 k), 16 (21 k), 10, 8, 0.
- `flag` = two signed bytes `(b0, b1)`, each in {-1, 0, +1}; upper bytes 0.

### Coordinates (asm -> bitstream plane of `cycloneiv_corpus.py`)

- `plane_frame = FX + 17 - (asm_frame - FX)`, FX = base frame of the LAB column holding `asm_frame` (`lifters/data/cycloneiv_ep4cgx150_geom.json`): the frame axis is mirrored inside every 35-frame LAB column.
- `plane_v = 6344 - asm_v`: the row axis is mirrored over the whole die (vendor row R runs opposite to the fitter Y; R = 91 - Y for H4 wires).
- Evidence: learner mux patterns (LI / R4 / C4 / C16 / R24, 2-bit) land inside one asm group 83 % with this map (46 % with identity, < 25 % with any plain shift / global mirror); asm routing bands sit at plane offsets 5..15 of the column (LI muxes at 6..8 / 9..11 / 12..15, C4 drivers at 12..15) and the sparse bands at -2..5 (C16 at +5, LOCAL_LINE +2, LE_BUFFER +1) and -10..-17 (LE input muxes); the 24 empty asm frames cover the LUT masks (-7..0) and FF config.
- Non-LAB columns (M9K, multiplier, IO) use the same formula with their synthetic FX; not verified there.

### Record / group semantics

- Record = one physical routing wire (source). Vendor name from icname (`H4R32C60RT[3]` = horizontal 4-LAB wire, row 32, column 60, right-going, index 3). Its groups = the destination muxes it feeds (H4: 5 columns, 18-22 groups; V4: 5 rows). Records 0..149,759 are empty (one per LE); 149,760.. are the LE_BUFFER outputs (`rec = base[I] + 90 * colrank(X) + Y`, colrank = LAB columns right-to-left, base learnt per I); H4 names start at 449,321.
- Group = one input of a two-level mux. Entry roles by `b0`: `+1` = the one-hot select bit of this input (always programmed 1); `-1` and `0` = the two second-level bits shared by the 12 inputs of the mux; a second-level bit is programmed 1 iff its `b1 == -1`. States of the `(b1(-1), b1(0))` pair: `(-1,+1)`, `(0,-1)`, `(0,0)` = the three second-level choices. `b1` of the select entry (0 or 1) carries no bit.
- A mux ("block", `cycloneiv_asm_decode.py prepare`) = the groups sharing the same second-level positions: 2,620,817 blocks. The plane selects input g iff g's programmed bits are all set and every other bit of the block is clear; 31.7 k groups fire in a corpus design, 99.9 % one per block.
- Groups whose entries are all `b0 = 0` except one select bit (the 4-groups listing a mux's four select bits) fire alongside the real input group and carry no source; the decode skips them. 2 / 6 / 12 / 16-groups (clock / IO / wide muxes) follow the same bit rule but are not yet attributed.
- The RCF names a wire by the column (R4) / row (C4) it is driven from, so one asm record has several RCF names (`H4R32C60RT[3]` = `R4:X55Y59I3` = `X57` = `X59`, driver dependent; LT/RT and the index also change with the driver column). Scoring therefore uses a learnt alias set per RCF `(type, I)` (`lifters/data/cycloneiv_ep4cgx150_asm_names.json`).

## icname body

- `u32 4, u32 N (729,374), u32 base | 0x80000000`, then N x (`u32 len, name, u32 v`): record id of the first name = base (449,321), then id += v (v = 1 for runs; a v with bit 31 set restarts at an absolute id).
- Then the same names again prefixed `XQ4/Q4_` (second table, same layout), then GCLK / RCLK / BIOCLK / TIOCLK / IOC / LEIM / HSSI names (16 M of the 50 M inflated).
- Families: H4 370,260, V4 263,952, H24 12,690, V16 12,402, HSSI 1,653, LEIM 1,385, RCLKR*, GCLK, BIOCLKCS, TIOCLKCS, IOC.

## routing.ddb (88 MB inflated; layout only, not decoded)

- Body `u32 4, 118, 92, 1802443` then a `DYGR_LOOKUP` nest of `(u32 65536|65537, 0, 2|6|12)` triplets (0..13.3 MB, 1,756 `INT_LOOKUP_OFFSET`), 13.3..19.2 MB small ints, `197688` (ROUTE_ELEMENT_TEMPLATE count) at 21,629,332 followed by 180 k x `6`, `1802443` at 22,469,513 followed by `-1, 0, -1, 0` and 5.4 MB of zeros (= 3 bytes per node), 27.9..40 MB u16-like data, 40..42 MB zeros, 43..61 MB large packed values (bit fields), 61..83.7 MB i32 with small magnitudes (the `int` / `unsigned short` arrays, 3,612,712 each = 2 x (N + 3,913)), 83.7..85.9 MB zeros, 85.9 MB..end signed deltas of ~1e5 (position-like).
- Byte-level segmentation: `tmp/cycloneiv`-style profile with 64 KB windows separates these regions cleanly; no per-array count fields (counts come from the enclosing structs), so the arrays have to be sized from the type table.
- The fan-in map (`DYGR_DETAIL::ROUTE_FANIN_MAP`, NODE_DATA count 0) is what would name every mux output; until it is decoded the block -> destination map is learnt from the oracle.

## Naming quirks found while scoring

- The RCF type of a source is not always the wire's physical class: at LI muxes ~6 % of 2-bit codes that the asm attributes to an `H4` record are named `C4:...` by the RCF (and vice versa), consistently per tile class; `H24` records appear as RCF `C16` and `V16` as `R24`. These are driver-mux names, so the alias sets carry cross-type forms.
- ~3 % of 3-groups carry `b0 = 0` on the select entry (first entry of the group); it is still the programmed select bit.

## Not decoded

- routing.ddb (fan-in map that would name mux outputs directly), place / pad / timing.
- Which wire a block drives is not in asm; learnt from the oracle by co-occurrence (block -> RCF destination per tile class).
- IO / clock-tree records (2 / 6 / 12 / 16-groups), M9K / multiplier columns.
