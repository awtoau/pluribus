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

## routing.ddb (88 MB inflated; node table, twin map, spans, section identities decoded; connectivity expansion open)

Readers: `scripts/cycloneiv_ddb_routing.py` (`nodes` / `twin` / `templates`), `scripts/cycloneiv_ddb_fanout.py` (corpus ground truth + assignment-hypothesis harness). Shared conventions in every per-node delta stream here:

- **Arithmetic is plain cumsum mod 2^31.** The earlier "restart rule" (`v < -2^30` restarts at `v + 2^31`) is this same arithmetic seen from a small accumulator; with mod-2^31 cumsum the `c` stream decodes in-range for ALL nodes (the old reading lost 29 %).
- **Ids stored +1**, running value `0` = NULL.

### Sections (byte offsets, stingray4)

- `0..16` header `u32 4, 118, 92, N = 1802443`.
- `16..21,629,332` **node table**: N x `(i16 dx, i16 dy, i32 c, i32 dn)` (`nodes` -> `tmp/ddb/stingray4_rt_nodes.npy`).
  - `cumsum(dx), cumsum(dy)` = tile (vendor grid x 0..117, y 0..91); node ids = asm record ids. **Vendor x = 115 - plane x**; y = plane y.
  - `cumsum(dn)` = offset of the node's fan-out list in the **in-memory expanded entry arrays** (`int` + `unsigned short`, 3,612,712 each in the type table), 2 offset units per entry; max offset/2 = 3,186,259. `dn == 2 x group count` for 290,512 records (empty records count 1 implicit group). The lists are **not byte-addressable in the file** - the loader expands them from the templates below (this is why every fixed base x unit indexing attempt failed).
  - `c`: mod-2^31 cumsum (+1 convention) -> per-node **node-id-valued** reference V, in range 0..N for ALL nodes; V = 0 (NULL) for every LE + 523,585 others; 362,754 distinct targets, repeated (every `RCLKR*CS29R*` is referenced by exactly 30 nodes). Reads as a designated fan-in-side neighbour (`H4R50C83RT[12] -> H4R49C87RT[13]` end-to-driver pairs); V is NOT in the node's own fan-out under any tested expansion, not a template anchor, not a flyweight back-ref (not unique).
- `21,629,332` `u32 197688`, i32 `-790746`, then 197,687 x `6` (constant) + 12,356 tail ints: per-family serialized containers - `(count, count, -count)` triples per family in id order (149760 LE, 299520 LEB+LL, 370260 H4, 263952 V4, 12690 H24, 12402 V16, 25920, 12960, ...), a leading `2717` (unidentified count), then packed ASCII class names. No per-node or per-template assignment data.
- `22,469,513` `u32 N`, then N x 12 bytes `(i32 f0, i32 f1, i32 f2)`: **twin / other-end map** (`twin` -> `stingray4_rt_twin.npy`). `cum_ids(f0)` = the record of the SAME WIRE's other end: `H4R90C119RT[0] -> H4R90C112LT[0]`; edge wires map to HSSI/HIO boundary records. NULL for ids 0..449,320 (LE/LEB/LL - not two-ended wires). Verified 1,440/1,440 icname pairs (same type, same row/col, span 1..30; direction letter and index may change with the end, as in the RCF alias sets).
  - `cumsum(f1)` = per-node small value 0..30: the wire's span (named pairs have span 1..30).
  - `cumsum(f2) mod 2^31` = per-node POINTER into the 44.1 MB table below (0 = none; max = its entry count - 2).
- `44,098,833..62,517,553` **sorted-id list table**: `u32 4604678, u32 0`, then 4,604,678 i32: 336,060 zero-sum delta records (each record's deltas sum to 0 via a final negative; the running cumsum emits a SORTED list of node ids +1). `f2` points per node at one list; lists are shared (flyweight); LE/LEB/LL lists are empty. Members cluster at family-boundary offsets, i.e. encode (family, within-family offset) pairs. Semantics open - per-node fan-in template is the best guess, but see the negatives below.
- `62,517,553..63,060,526` serialized `DYGR_LOOKUP` objects (class-name strings + ~197k small records; unparsed).
- `63,060,526..EOF (88,157,812)` **element-template stream** (`templates` -> `stingray4_rt_tpl.npz`): back-to-back records
  `[u32 na][na x u16 attrs][i16 e][u32 0][i16 e][i8 flag][u16][u32 nd][u16 first][(nd-1) x i32 deltas]`, `e == nd - na`, `first` always 0.
  - Parse with resync: 197,583 of the 197,688 `DYGR_ROUTE_ELEMENT_TEMPLATE`; attr sum 3,611,175 / entry sum 3,613,697 vs 3,612,712 each in the type table; 37 unparsed stretches, 610 bytes total, mostly 63.06..63.12 MB where the short LE/LEB/LL templates use a variant (i32 delta, i32 attr) pair coding.
  - attrs (u16, one per entry) are 0 in all templates sampled.
  - Delta values are structured as `k x 10620 +- small` (10,620 = 118 x 90 = one uniform family block), so entries encode (family hop, position offset) in a canonical uniform-grid id space.
  - **The expansion rule is NOT `dests = r + cumsum(0, deltas)`.** That held only in the LEB-anchored window where it was first seen and does not generalize: for corpus-grounded records (exact LE_BUFFER source ids, RCF-observed dests) NO template of any size under that rule gives a local dest set or covers the observed dests.

### Type table (zlib trailer) - what the sections are

`DYGR_ROUTE_INFO_BODY` 1; `DYGR_DETAIL::ROUTE_FANIN_MAP` 1 with `::NODE_DATA` sizeof 12 = the node table rows (so the 12-byte node records belong to a FAN-IN map); `DYGR_ROUTE_ELEMENT_TEMPLATE` 197,688 sizeof 32; payload `int` + `unsigned short` 3,612,712 each; a 5-deep `DYGR_LOOKUP<...DYGR_INT_LOOKUP_OFFSET>` tree (1 / 1,004 / 330 / 846 / 4,178 lookups, leaf `DYGR_INT_LOOKUP_OFFSET` 1,756) with `DYGR_LOOKUP_TEMPLATE` flyweights (1/67/94/47/26) = the get_global_id-style keyed lookup; `DYGR_ROUTE_BLOCK_INTERFACE` 28, `_NODE` 983, `BLOCK_IO_MAPPING_ENTRY` 7,502.

### Open: node -> connectivity expansion (assignment + delta semantics)

Which template a node instantiates AND how template deltas map to records are still open. Corpus ground truth (exact: LE_BUFFER record = `base[I] + 90*colrank(X) + Y`, 111,530 observed sources, 1.6 M wire arcs from 2,984 designs - `cycloneiv_ddb_fanout.py observe/gt`) rejects, in addition to the older negatives:

- `dests = r + cumsum` in global id space: no local template of ANY size anchors at a corpus-grounded record (0 of 197,583 for several probes).
- Canonical-block space (`fam x 10620 + x*90 + y`, all 24 axis-mirror/major variants): no observed-dest coverage.
- Restart/absolute entries in template deltas: only 115 deltas < -2^30 (2 junk templates) - not the mechanism.
- Fan-in reading (template lists = sources of the owner, subset test over exact LEB sources, both id and canonical units, both mirrors): no consistent (record, template) matches.
- f2-list expansions as fan-in/fan-out via anchor shifting (anchor = lowest node id sharing the pointer; global-id shift, tile shift, within-family-index shift): no corpus matches.
- `nd == ng` (asm group count) need not hold; `dn == 2 x ng` holds for exactly 290,512 records only.
- The per-(RCF type, I) name rules are NOT constant offsets: wires are driven at varying span positions and the two end records (twins) sit in different families (47 inconsistent rules; mass-applying them produced 442 template-membership violations).
- An intersection bootstrap over learnt-alias candidate sets produces FALSE unique assignments (templates whose scattered entries happen to cover alias junk); corpus subset tests must use position-window candidates, which keep the true record but did not yield unique templates under any tested expansion.

Next lead: deserialize the 5-level `DYGR_LOOKUP` tree (region 2 + the 62.5 MB object block); its leaf `DYGR_INT_LOOKUP_OFFSET` values are the likely (element, tile) -> expansion keys, and `libccl_dygr` symbol names in the Quartus binaries should pin the field layout.

Until then the block -> destination map stays learnt from the oracle; the twin map already gives the RT/LT (driver-dependent) alias pairing without the learnt alias sets, and `f1` gives exact spans.

## Naming quirks found while scoring

- The RCF type of a source is not always the wire's physical class: at LI muxes ~6 % of 2-bit codes that the asm attributes to an `H4` record are named `C4:...` by the RCF (and vice versa), consistently per tile class; `H24` records appear as RCF `C16` and `V16` as `R24`. These are driver-mux names, so the alias sets carry cross-type forms.
- ~3 % of 3-groups carry `b0 = 0` on the select entry (first entry of the group); it is still the programmed select bit.

## Not decoded

- routing.ddb (fan-in map that would name mux outputs directly), place / pad / timing.
- Which wire a block drives is not in asm; learnt from the oracle by co-occurrence (block -> RCF destination per tile class).
- IO / clock-tree records (2 / 6 / 12 / 16-groups), M9K / multiplier columns.
