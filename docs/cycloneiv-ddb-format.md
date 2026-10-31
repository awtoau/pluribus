# Cyclone IV GX `.ddb` (Quartus device database) format

Source: `quartus-25.1/quartus/common/devinfo/cycloneivgx/ddb_stingray4_*.ddb` (STINGRAY4 = EP4CGX150, same files serve EP4CGX110; own licensed install, analysed for interoperability, never redistributed or committed).
Readers: `scripts/cyclonev_ddb_decode.py` (container, shared with Cyclone V), `scripts/cycloneiv_ddb_asm.py` (asm records), `scripts/cycloneiv_asm_prep.py` (raw record / group / block tables).
Measured 2026-10-26. Cyclone V sibling: [cyclonev-ddb-format.md](altera/cycloneV/cyclonev-ddb-format.md).

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
- `flag` = two signed bytes `(b0, b1)`, each in {-1, 0, +1}: i8 DELTAS of the 1-bit fields F0 (use-encoded) and F1 (encoded-high) vs the previous bit; value = running sum over all entries & 1 (DYGR_ROUTE_ASM_BIT::operator<<, libddb_dygr 0x2caf80). Upper bytes 0 (variant / tag fields constant).

### Coordinates (asm -> bitstream plane)

Retired: the AFX / per-column mirror model (frame and row mirror formulas) was refuted and removed (#165, `docs/cycloneiv-retired-coordinate-model.md`). Current rule: `docs/cycloneiv-clean-pipeline.md` A3-A5.

- Removed: the AFX / per-column mirror formulas and their evidence (fitted, refuted; E-C2).

### Record / group semantics

- Record = one physical routing wire (source). Vendor name from icname (`H4R32C60RT[3]` = horizontal 4-LAB wire, row 32, column 60, right-going, index 3). Its groups = the destination muxes it feeds (H4: 5 columns, 18-22 groups; V4: 5 rows). Records 0..149,759 are empty (one per LE); 149,760.. are the LE_BUFFER outputs (`rec = base[I] + 90 * colrank(X) + Y`, colrank = LAB columns right-to-left, base learnt per I); H4 names start at 449,321.
- Group = bits that make one edge conduct (vendor `get_bits_from_source_to_dest`, libddb_dygr 0x23bfe0): entry value = 1 if F0 clear (one-hot select), else F1.
  - The destination's exclusion groups (the last groups of its record, no edge) list every mux bit of the destination; those not in the edge's list must be 0.
  - Replaces the earlier reading "b0 == +1 select, b1 == -1 set" (delta bytes taken as values; fitted, see docs/reversing-errata.md).
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

### asm group <-> graph edge (block -> output-wire map)

`scripts/cycloneiv_ddb_blockmap.py` (`build`); the old `ddb_trace` export / score is retired (#165).

- **Rule: group k of source record r == fan-out edge k of r; the last `ng - ne` groups are
  select-bit pseudo-groups.** dest = `V(r) + offs[k]`. 14,862,095 real groups, 2,429,196 pseudo.
  - Pseudo-groups are always the tail: H4 `(..., 4, 2)`, V4 `(..., 6, 2)`, H24 / V16 `(..., 16, 2)`;
    LE_BUFFER / LOCAL_LINE have none (`ng == ne` for all 299,560 records).
- Self-check without any oracle: a mux (block) must name ONE dest wire.
  - 99.19 % of 1,379,388 blocks single-dest; keyed by (block, select-bit position) 99.74 % of
    5,421,809 units. The 14,105 multi-dest units are blocks of group size 0 / 1 / 3 shared across
    several muxes (known: one block can hold several muxes); not enumerated further.
  - A 30-input mux spans several blocks: 186,723 dest records are driven by units of >1 block;
    exactly one of them fires, so the tracer unit is the dest record.
- Specimen agreement (`blockmap.py specimens`, 116 exact entries applied to every block of their class,
  3,490 wire / 6,845 LI outputs): wire matched 3,479 / missing 1 / extra 5 / wrong 5 (99.685 %).
  LI matched 4,770 / missing 1 / extra 1,073 / wrong 1,073 (68.96 %; every wrong output carries one extra).
  - Wrong LI outputs by key (`tmp/cycloneiv_ddb_specimen_disagree.json`): class entries `12,-13|12,-12`
    (LI 31, 219 blocks) and `6,-1|6,0` / `6,29|6,30` / `6,-13|6,-12` (LI 0 / 9 / 3, 12-23 blocks each)
    where ddb names an H4 / V4 wire or another LI; all tile entries at tile row 0 (block tile clipped
    to the IO row). Not adjudicated: both sides are exact-claimed, they cannot both be right.
- LI element = `enum 282`, template index 0..37 per LAB tile; (vendor x, y, index) is unique. Vendor x = fitter X (A8, `docs/cycloneiv-clean-pipeline.md`); the earlier "115 - X" mirror and "RCF LI column vs vendor LI tile unresolved" statements are removed (E-C2).

### Open

- LI-band specimen conflict above (ddb vs specimen on 6 class keys).
- Pin trace on the exact graph is below the old tracers (see issue #141 for the gate numbers): the
  asm group SELECTION decode (which group of a block fires) is the limiting piece, not the map.
- RCF `R4 I28-31` dests resolve to unnamed records (enum 282); name them via element enum / index.
- 150 edge-column scoring misses of the `check` gate (position-window artifact).

## Naming quirks found while scoring

- The RCF type of a source is not always the wire's physical class: at LI muxes ~6 % of 2-bit codes that the asm attributes to an `H4` record are named `C4:...` by the RCF (and vice versa), consistently per tile class; `H24` records appear as RCF `C16` and `V16` as `R24`. These are driver-mux names, so the alias sets carry cross-type forms.
- A select entry with `b0 = 0` is F0 unchanged from the previous entry (still clear = one-hot).

## asmdb (settings database; partly decoded 2026-10-30, #165)

Same container and stream layer as routing.ddb (type id << 2 = NEW pointer tag, content deferred to per-class pools; vectors = u32 count + delta ints, element 0 delta against the previous owner's element 0).  Body 5,350,270 B; 29 classes (die root, 8 block-info, ~6.3 k arch groups, ~37.6 k muxes).  Static decode only; reader is local (`vendor-analysis/`, gitignored).

- Die head: total bits 39,040,976, 31,060 cff bits, 160 option bits; 8 block types; 6,087 + 225 group pointers (277 calc / 4,893 + 103 std / 913 + 119 dumb / 4 + 3 map classes); 2,518 + 35 forced-bit words; main stream ends at body offset 0x949c, then pools to EOF.
- Address model (per block instance, "traditional" style): `addr = (q + hi) * 6154 + (r + lo)` for a block-local bit `q * 6154 + r`; `(hi << 16) | lo` is a per-instance u32 cell in a vector.
  - Bits with top bits `11` are literal flags, `101` are offset by a second per-instance vector (not decoded).
- Instance cells found: LAB 9,360 (104 columns x 90 rows), M9K 720 (8 x 90), MUL 360 (4 x 90). Row r = Y - 1; LAB columns paired with the instance cell vector ascending with X (rank 0 = lowest X; A3, `docs/cycloneiv-clean-pipeline.md`).
  - `hi[r] = 6252 - 70 r`.
- LUT INIT bits: address = `(hi[r] + dx) * 6154 + lo[c] + dy` as the vendor formula reads (`ASMDB_BLOCK_INFO::calculate_bits_traditional` @ libdb_asmdb 0x8e8a4, key 1 cell = `hi << 16 | lo`), `(dx, dy)` = blkrba `(x_cum, y_cum)` of `RBLUT{k}`; 1,023 / 1,023 sites match the oracle with no sign flip and no constant. One local table serves all 9,360 LABs.
  - Earlier local-bit, frame-offset and column-anchor statements are removed (fitted to the retired model; a +3 seen in the first pool extraction does not exist in the clean walk, E-A3 in `docs/reversing-errata.md`).
- Open: IO column cells, the second per-instance vector, calc-group to block association and the mux class pools other than the LAB LUT run are not decoded.  The 88 double-offset frames next to M9K / MUL are expected where two instances' local ranges overlap (not yet shown).
- Dirt file (3 KB): 3 small classes (string / integer / inner), not decoded.

## Not decoded

- routing.ddb (fan-in map that would name mux outputs directly), place / pad / timing.
- Which wire a block drives is not in asm; learnt from the oracle by co-occurrence (block -> RCF destination per tile class).
- IO / clock-tree records (2 / 6 / 12 / 16-groups), M9K / multiplier columns.
