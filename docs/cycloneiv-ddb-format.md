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

## routing.ddb (88 MB inflated; FULLY DECODED - exact node -> fan-out / fan-in graph)

Decoded 2026-10-28 from the vendor serializers in `quartus/linux64/libddb_dygr.so` + `libdb_pdb.so`
(full `.symtab` present; schemas extracted by `scripts/cycloneiv_ddb_symdump.py`).
Readers: `scripts/cycloneiv_ddb_routing.py fanout` (exact, self-validating -> `tmp/ddb/<die>_rt_fanout.npz`);
`nodes`/`twin`/`templates` are the older partial readers, superseded.
Gate: `scripts/cycloneiv_ddb_fanout.py check`.

### PDB stream layer (libdb_pdb.so, PDB_SEGMENT_READER/WRITER)

Objects serialize via `operator<<(PDB_SEGMENT_TEMPLATE<PDB_DDB_SEG_BASE>&)` making vtable calls;
one function both reads and writes (reader/writer vtables at `libdb_pdb.so` 0x1e4b8 / 0x1e378).

- `xfr_char/short/int/long` - plain little-endian 1/2/4/8 B.
- `xfr_*_delta` - same width, value = stored + **same field of the previous object of the same class**
  (per-class `last_this` chain; first object deltas against a zeroed default). Plain integer wrap,
  NOT mod 2^31 (the earlier mod-2^31 / "restart rule" readings were approximations of this).
- `xfr_field_v(value, width_bits, prev)` - bitfield delta: stored in the smallest signed int covering
  the width (<=8 -> i8, <=16 -> i16, else i32); caller masks to width.
- `xfr_new_array(ptr, thunk, count)` - NO count in stream; `count` elements, each via the element
  thunk; element 0 deltas against **the previous owner's same array element 0**, element i against
  element i-1. `PDB_STL_CLASS_THUNK<int>` elements = `xfr_int_delta`, `<unsigned short>` = `xfr_short_delta`.
- `xfr_ptr(obj, thunk)` - u32 tag: `0` = NULL; `12` = NEW object -> next registry slot (slots start
  at 1, per class, in first-use order; the NEW tag does NOT move the delta cursor); `(d<<2)|2` =
  reference, registry cursor += d (signed). Object CONTENT is deferred: all objects of a class are
  serialized back-to-back in registration order in pools at the end of the file.
- `xfr_new` - inline object (content serialized immediately).

### DYGR_ROUTE_INFO_BODY schema -> section map (byte offsets, stingray4)

Field order from `DYGR_ROUTE_INFO_BODY::operator<<` (run `symdump` for the full annotated list):

- `0..16`: root ptr tag `4`(legacy NEW form), `m_nx` 118, `m_ny` 92, element-vector count N = 1,802,443.
- `16..21,629,332` `m_route_element_list`: N x 12 B **DYGR_ROUTE_ELEMENT**
  `(i16 d m_x, i16 d m_y, i32 d V, u32 ptr-tag m_template)`.
  - `cumsum(m_x), cumsum(m_y)` = home tile (vendor grid x 0..117, y 0..91); ids = asm record ids;
    vendor x = 115 - plane x, y = plane y.
  - `V` (named `m_fanout_edge_base` in the binary; bit 31 = has-fanout flag, mask it) =
    **id of the element's FIRST (lowest) fan-out destination**; 0 = no fan-out
    (149,760 LE + 523,585 others = 673,345, exactly the elements whose template is empty).
  - ptr tag -> 0-based template id (tag chain above; 197,688 NEW, 1,604,755 references, 0 NULL).
- `21,629,332..22,420,088` `m_route_element_templates`: u32 197,688 + that many ptr tags
  (first `-790746` = jump back to slot 1, then `6` = +1 each: registration order).
- `22,420,088..22,469,513` `m_route_element_list_info` (per-family `(i32 d start_index, i32 d num)`),
  `m_chunked_lookup_info` ptr, `m_route_block_types`, `m_block_interfaces` (the inline ASCII names),
  `m_block_io_mappings`, `m_family_enum`, `m_third_dimension_enum`, `m_tile_x_offsets`,
  `m_hipi_reg_to_mux_hash`.
- `22,469,513..44,098,833` `m_fanin_map` (inline `DYGR_DETAIL::ROUTE_FANIN_MAP`): u32 N + N x 12 B
  **NODE_DATA** `(i32 d m_fanin_edge_base, i32 d m_num_fanin_edges, i32 d m_starting_offset_idx)`:
  - `m_fanin_edge_base` (mask bit 31) = **first (lowest) fan-in SOURCE id**; for two-ended wires this
    is the wire's other end, which is what the old "twin map" reading verified (1,440/1,440 named pairs).
  - `m_num_fanin_edges` = fan-in count 0..30 (the old "span" reading).
  - `m_starting_offset_idx` = index into `m_offsets`.
- `44,098,833..62,517,549` `m_offsets`: u32 4,604,678 + that many chained i32 deltas ->
  shared (flyweight) **relative fan-in lists**: `sources(n) = fanin_base(n) + (list - list[0])`,
  sorted ascending. Verified exact on 7,143/7,143 sampled nodes against the inverted fan-out.
- `62,517,549..63,120,844` deferred object pools: `DYGR_ROUTE_LOOKUP_INFO_BODY` -> 5-deep
  `DYGR_LOOKUP<..DYGR_INT_LOOKUP_OFFSET>` tree (the (enum,x,y,z,index) -> element-index lookup;
  not needed for connectivity), block types/interfaces/io mappings.
- `63,120,844..EOF (88,157,812)` deferred pool of 197,688 **DYGR_ROUTE_ELEMENT_TEMPLATE**, each:
  `i16 d m_element_enum, i16 d m_num_edges, i16 d m_z, i16 d m_index, i16 d(16b) m_first_purely_redundant_edge,`
  `i8 d(8b) m_length, i8 d(4b) m_metal_layer, i8 d(4b) m_direction,`
  `u16 count, count x i32 d m_fanout_list_offsets, u16 count, count x u16 d m_fanout_to_positions`.
  Pool start = EOF - (17 x 197,688 + 6 x 3,612,712); parses with zero resync, counts == type table.
  `m_fanout_to_positions` is all zeros on disk (input positions are assigned at load from the sorted
  fan-in lists); edge order is canonical insertion order, not dest-sorted.

### Fan-out expansion (the whole point)

`DYGR_ROUTE_ELEMENT::add_fanout(dest, pos)` stores `offsets[k] = dest - first_dest` and keeps
`first_dest` in the element, so:

- **dests(element e) = V(e) + m_fanout_list_offsets(template(e))**; `offsets[0] == 0` for all
  197,688 templates. Templates are translation flyweights - this anchoring at the first DEST
  (not at the element's own id) is why every earlier `r + cumsum` expansion failed.
- Expansion: 14,862,095 edges, all dests in 449,321..1,802,442 (wire/mux records only).

### Validation (2026-10-28, `fanout` + `check`)

- Structural: every per-template count == `m_num_edges`; both array counts equal; pool ends exactly
  at EOF; total edges 3,612,712 == type table; `V == 0` iff template empty (0 mismatches / 1.8 M).
- **Fan-in inversion: inverted fan-out counts == `m_num_fanin_edges` for ALL 1,802,443 nodes**;
  sampled fan-in lists match `m_offsets` exactly. The graph is self-consistent in both directions.
- Corpus (2,984 designs, LE_BUFFER-rooted RCF arcs, exact source records): matched 264,937 /
  missing 150 / total 265,087 = **99.943 %**; all 150 misses are at vendor edge columns (fitter
  X >= 112) where the position-window candidate sets clip at the die edge - a scoring-window
  artifact, not a decode fault (extra/wrong are not scoreable here: RCF arcs are a subset of the
  full fan-out).
- asm cross-check: template edge count == asm group count minus the 0..3 select-bit pseudo-groups
  (diff histogram -2: 1,029,768, 0: 487,975, -1: 242,220, -3: 42,480; never positive). The old
  `dn == 2 x ng` observation was the ptr-tag stream, now exactly decoded.

### Type table (zlib trailer) - class inventory

`DYGR_ROUTE_INFO_BODY` 1; `DYGR_DETAIL::ROUTE_FANIN_MAP` 1 + `::NODE_DATA` 1,802,443 x 12 B;
`DYGR_ROUTE_ELEMENT_TEMPLATE` 197,688 x 32 B; payload `int`/`unsigned short` 3,612,712 each;
5-deep `DYGR_LOOKUP<..DYGR_INT_LOOKUP_OFFSET>` tree (1/1,004/330/846/4,178, leaves 1,756) with
`DYGR_LOOKUP_TEMPLATE` flyweights; `DYGR_ROUTE_BLOCK_INTERFACE` 28, `_NODE` 983,
`BLOCK_IO_MAPPING_ENTRY` 7,502.

### Open

- asm fired-group <-> graph-edge correspondence (template edges are in canonical order and count
  real groups exactly, so the block -> output-wire map should follow): #141 track 2 remainder.
- The 150 edge-column scoring misses: widen/repair the edge-column candidate model when the map lands.
- RCF `R4 I28-31` dests resolve to unnamed records (enum 282, zero fan-out, co-located with the
  named H4; ids 1.1-1.6 M); the `XQ4/Q4_` icname table re-names the SAME ids 449,321.., so these
  stay unnamed in icname - name them via the lookup tree or the element enum when needed.

## Naming quirks found while scoring

- The RCF type of a source is not always the wire's physical class: at LI muxes ~6 % of 2-bit codes that the asm attributes to an `H4` record are named `C4:...` by the RCF (and vice versa), consistently per tile class; `H24` records appear as RCF `C16` and `V16` as `R24`. These are driver-mux names, so the alias sets carry cross-type forms.
- ~3 % of 3-groups carry `b0 = 0` on the select entry (first entry of the group); it is still the programmed select bit.

## Not decoded

- routing.ddb (fan-in map that would name mux outputs directly), place / pad / timing.
- Which wire a block drives is not in asm; learnt from the oracle by co-occurrence (block -> RCF destination per tile class).
- IO / clock-tree records (2 / 6 / 12 / 16-groups), M9K / multiplier columns.
