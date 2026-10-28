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

## routing.ddb (88 MB inflated; node table, twin map and template contents decoded; node->template assignment open)

Reader: `scripts/cycloneiv_ddb_routing.py` (`nodes` / `twin` / `templates`). Shared conventions found in every delta stream here:

- **Restart rule:** a delta `v < -2^30` restarts the accumulator at `v + 2^31` (plain negative deltas also have bit 31 set, so the old "bit-31 = restart" reading was wrong).
- **Ids stored +1**, `0` = NULL.

### Sections (byte offsets, stingray4)

- `0..16` header `u32 4, 118, 92, N = 1802443`.
- `16..21,629,332` **node table**: N x `(i16 dx, i16 dy, i32 c, i32 dn)` (`nodes` -> `tmp/ddb/stingray4_rt_nodes.npy`).
  - `cumsum(dx), cumsum(dy)` = tile (vendor grid x 0..117, y 0..91); node ids = asm record ids. **Vendor x = 115 - plane x**; y = plane y.
  - `cumsum(dn)` = offset of the node's fan-out list in the **in-memory expanded entry arrays** (`int` + `unsigned short`, 3,612,712 each in the type table), 2 offset units per entry; max offset/2 = 3,186,259. `dn == 2 x group count` for 290,512 records (empty records count 1 implicit group). The lists are **not byte-addressable in the file** - the loader expands them from the templates below (this is why every fixed base x unit indexing attempt failed).
  - `c`: delta stream (restart rule above, +1 convention, NULL for every LE) -> a per-node **node-id-valued** reference V: restart values are all valid ids (449,412..1,802,438); locally V tracks the node (V = r + const within a run; typical deltas +-10620+-1 = +-(118x90)+-1 = one H4-subtype block +- one tile). Suspected template/driver anchor; plain cumsum drifts out of range for ~29 % of nodes, so the full convention is still open. V is 1:1 where checked (not a shared template pointer), V(V) != V.
- `21,629,332` `u32 197688`, i32 `-790746`, then 197,687 x `6` + 12,356 tail ints (2717, zeros, few 1/3/8/16/24/1<<26/0x50000000) - per-template small ints, not resolved.
- `22,469,513` `u32 N`, then N x 12 bytes `(i32 f0, i32 f1, i32 f2)`: **twin / other-end map** (`twin` -> `stingray4_rt_twin.npy`). `cum_ids(f0)` = the record of the SAME WIRE's other end: `H4R90C119RT[0] -> H4R90C112LT[0]`; edge wires map to HSSI/HIO boundary records. NULL for ids 0..449,320 (LE/LEB/LL - not two-ended wires). Verified 1,440/1,440 icname pairs (same type, same row/col, span 1..30; direction letter and index may change with the end, as in the RCF alias sets). f1/f2 = small per-node ints, unresolved.
- `44,098,833..~63.06 MB` lookup tables (`DYGR_LOOKUP` nests; affine-looking triplets `183510, 90, 180, <base>...` = per-(type, tile) tables, probably (elem, x, y, i) -> id for `get_global_id`), zeros, packed tables. Not needed for fan-outs so far.
- `~63,060,526..84 MB` **fan-out template stream** (`templates` -> `stingray4_rt_tpl.npz`): back-to-back records
  `[u32 na][na x u16 attrs][i16 e][u32 0][i16 e][i8 flag][u16][u32 nd][u16 first][(nd-1) x i32 deltas]`, `e == nd - na`, `first` always 0.
  - **Dests of a node r instantiating a template = r + cumsum(0, deltas)** (owner-relative, cumulative). Verified: LEB templates give 6 same-tile dests (+9360 steps = +1 LE I-region) matching the 6 asm groups exactly for records in the anchored window; H4 templates (nd 18..23) give compact 5-column footprints; one H4 blob matched a cross-check record's group tiles as sub-multiset with the known per-dest-type bit-tile skew.
  - Parse with resync: 197,583 of the 197,688 `DYGR_ROUTE_ELEMENT_TEMPLATE`; attr sum 3,611,175 / entry sum 3,613,697 vs 3,612,712 each in the type table; 37 unparsed stretches, 610 bytes total, mostly 63.06..63.12 MB where the short LE/LEB/LL templates use a variant (i32 delta, i32 attr) pair coding seen at 63,072,300: `(-140400,100) (9360,6) (9360,2)x4`.
  - attrs (u16, one per entry) are 0 in all templates sampled; the per-entry mux-input attribute may live in the pair-coded variant or elsewhere.

### Open: node -> template assignment

The expansion (which template each node instantiates) is the remaining piece; candidates are `c`/V, the 21.6 MB "6" section and the 44.1 MB lookups. Negative results, so you don't repeat them:

- No fixed base x unit addresses the lists: scanned ALL byte bases x units {1,2,3,4,6,8} (phase A, 96-sample near-own-tile predicate) and all bases 22..66 MB with exact tile-multiset scoring at unit 4 (phase B, 48 samples) - only node-table aliasing artifacts pass. Base 61,807,052 + 4 x off matches the LEB window (162/74,932 records exact) then drifts negative and dies by off ~1.4 M: the file order is template-first-use, not node order.
- Content-locating 60 H4/V4 k>=15 lists as stride-8 windows (exact and translation-tolerant tile shapes) over 44..88 MB: zero hits - their deltas are contiguous i32 runs inside template records, not (d, attr) pairs.
- `V // 10620` is not a global template id (LEB and H4 nodes collide at T=44); V is not a representative-node fixpoint map (V(V) != V, V unique per node where checked).
- asm group tiles (select-bit tile) vs dest node tiles carry per-dest-type skews (modes (0,+1) and (-4,+1)); an exact-tile cross-check needs those skews modelled per family.

Until assignment is decoded the block -> destination map stays learnt from the oracle; the twin map above already gives the RT/LT (driver-dependent) alias pairing without the learnt alias sets.

## Naming quirks found while scoring

- The RCF type of a source is not always the wire's physical class: at LI muxes ~6 % of 2-bit codes that the asm attributes to an `H4` record are named `C4:...` by the RCF (and vice versa), consistently per tile class; `H24` records appear as RCF `C16` and `V16` as `R24`. These are driver-mux names, so the alias sets carry cross-type forms.
- ~3 % of 3-groups carry `b0 = 0` on the select entry (first entry of the group); it is still the programmed select bit.

## Not decoded

- routing.ddb (fan-in map that would name mux outputs directly), place / pad / timing.
- Which wire a block drives is not in asm; learnt from the oracle by co-occurrence (block -> RCF destination per tile class).
- IO / clock-tree records (2 / 6 / 12 / 16-groups), M9K / multiplier columns.
