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

- `plane_frame = FX[x] + 17 - (asm_frame - AFX[x])`: the frame axis is mirrored inside every column band.  **AFX ≠ FX near special columns**: the asm frame axis lays columns out differently around M9K / MUL — on EP4CGX150 seven LAB columns (22, 35, 51, 64, 80, 93, 109 region) sit inside the plane's M9K frame spans and the plain-FX mirror decoded them to nothing (found by the first #141 specimen).  `cycloneiv_asm_decode.afx_map` derives AFX per column from the data: V4/V16-record entries vote their column (vendor C = fitter x + 2), the per-column fa-histogram peak sits at a fixed band offset (die-wide mode), AFX = peak − offset.  Valid band offsets 0..17; out-of-band entries (M9K bulk / interface, 1.5 M of 51.5 M) are dropped, never fire.
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

## routing.ddb (88 MB inflated; node table decoded, fan-out lists not)

- Body `u32 4, 118, 92, N = 1802443` (version, columns, rows, nodes), then the **node table**: N x 12 bytes `(i16 dx, i16 dy, i32 c, i32 dn)` at offset 16..21,629,332 (`scripts/cycloneiv_ddb_routing.py nodes` -> `tmp/ddb/stingray4_rt_nodes.npy`).
  - `cumsum(dx), cumsum(dy)` = the node's tile in the vendor grid, x 0..117, y 0..91; node ids are the asm record ids (same N, same order: LE nodes 0..149,759 run (1,1)..(116,90) column-major, LE_BUFFER from 149,760 restarts at (1,1), H4 from 449,321 at (0,1)). **Vendor x = 115 - plane x** (node (1,1) has its asm groups in plane column 114; (22,20) in 87..93); y = plane y (a C4's groups spread over y-1..).
  - `dn` is a delta: `cumsum(dn)` = offset (in ints) of the node's fan-out list; LE nodes advance by 2 (one fan-out, 2 ints), LE_BUFFER by 12 (6 fan-outs = the 6 asm groups) but then -10 (lists are shared: the same offset serves several nodes = the `DYGR_ROUTE_ELEMENT_TEMPLATE`s, 197,688 of them); for 290,512 records `dn/2` equals the asm group count exactly, for the rest the node has fan-outs without CRAM bits.
  - `c` is a delta with bit-31 restarts (0 for every LE, then +-10620+-1 = +-(118 x 90)+-1 alternating): a template / list reference in units of the die grid, not resolved.
- After the node table: `u32 197688` then 210,044 ints (197,690 x `6`, 12,070 x 0, a few 8/16/24/1<<26) = the template section (serialisation of `ROUTE_ELEMENT_TEMPLATE`, sizeof 32, not understood); `u32 1802443` at 22,469,513, `-1, 0, -1, 0`, then 1,347,963 ints of zeros; from 27,861,369 an int stream with bit-31 restarts and repeating 12-int motifs (`1168843, -4, 7, 1, 0, 0, -1168841, 7, 3, 1, 0, 10..`), 1,168,843 = the id distance H4 -> LI region, so these are fan-out entries (dest-id deltas + attributes); the list offsets from `cumsum(dn)` do not index this stream directly (tried bases 22,469,517 and 27,861,369: the 6-fan-out LE_BUFFER list reads `12, 37441, 3, 9, -93689, 0, -33, 93691, 0, 12, -37439, -3`; 37,441 = 4 x 9,360 + 1 looks like a LAB-indexed id delta, but no pairing reproduces the asm group tiles). 40..42 MB zeros, 43..61 MB packed bit fields, 61..83.7 MB i32 of small magnitude (the `int` / `unsigned short` arrays, 3,612,712 each), 83.7..85.9 MB zeros, 85.9 MB..end signed deltas of ~1e5.
- The fan-out / fan-in lists are what would name every mux output; until they are decoded the block -> destination map is learnt from the oracle. Node tile + type range + order within the tile already give a physical name for every node (not yet wired in).

## Naming quirks found while scoring

- The RCF type of a source is not always the wire's physical class: at LI muxes ~6 % of 2-bit codes that the asm attributes to an `H4` record are named `C4:...` by the RCF (and vice versa), consistently per tile class; `H24` records appear as RCF `C16` and `V16` as `R24`. These are driver-mux names, so the alias sets carry cross-type forms.
- ~3 % of 3-groups carry `b0 = 0` on the select entry (first entry of the group); it is still the programmed select bit.

## Not decoded

- routing.ddb (fan-in map that would name mux outputs directly), place / pad / timing.
- Which wire a block drives is not in asm; learnt from the oracle by co-occurrence (block -> RCF destination per tile class).
- IO / clock-tree records (2 / 6 / 12 / 16-groups), M9K / multiplier columns.
