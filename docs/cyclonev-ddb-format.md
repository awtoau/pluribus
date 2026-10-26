# Cyclone V `.ddb` (Quartus device database) format

Source: `quartus-25.1/quartus/common/devinfo/cyclonev/` (Quartus Prime Lite 25.1std.0 Build 1129, own licensed install; analysed for interoperability).
Decoders: `scripts/cyclonev_ddb_decode.py` (container), `scripts/cyclonev_ddb_asm.py` (asm records + comparison). Tests: `tests/test_cyclonev_ddb.py`.
Issue: #103 (EPIC), #108 (survey). Measured 2026-10-26.

## Container (all 2,708 / 2,709 files; `check --dir` = 0 failures, peak RSS 144 MB, 33 s)

All integers little endian. Fixed 0x73-byte header, then two compressed streams.

| offset | size | field |
|---|---|---|
| 0x00 | u32 | 0x14 (offset of the version string) |
| 0x04 | u32 | `0x0bad` \| kind<<16: kind 1 (routing/asm/icname/place/timing/crosstalk/gid_database), 7 (hdr/pad/pkg/part_info/dmf/fdi/...), 9 (asmdb, jspice) |
| 0x08 | u32 | 0 |
| 0x0c | u16,u16 | 0x73, 0x73 (header length) |
| 0x10 | u32 | 0x3c = string length counting one NUL that is not stored |
| 0x14 | 59 B | `Version 25.1std.0 Build 1129 10/21/2025 SC Standard Edition` (no NUL) |
| 0x4f | u64 | inflated size of the body |
| 0x57 | u64 | absolute file offset where the body stream ends = where the trailer stream starts |
| 0x5f | u64 | inflated size of the trailer |
| 0x67 | u32 | codec: 0 = zlib, 1 = xz |
| 0x6b | u64 | file size |
| 0x73 | | body stream (to `body_end`), then trailer stream (to EOF) |

- Codec by (kind, codec) over the whole tree: (1, zlib) 47 files, (7, xz) 2,590, (9, zlib `78 da`) 68, (7, zlib) 2, (1, xz) 1.
- **Body (zlib):** deflate with sync flushes, no final block, no adler32; ends with `00 00 ff ff` exactly at `body_end`. Stock `zlib` fails with "invalid stored block lengths" (~99.4 % of the output) only when the caller feeds past `body_end`: the trailer's own `78 01` header parses as a stored block. That was the survey's "error near the end". Cut at `body_end` and there is no error (inflated size == header field in every file).
- **Body (xz):** one complete `.xz` stream.
- **Trailer = type table**, same codec: `u16 count`, then per type `u16 id (1..count)`, `u32 sizeof` (in-memory C++ struct), `u32 layout crc`, `u32 count`, `u32 version`, `u32 namelen`, `name[namelen-1]` (no NUL).
  - `count` = number of elements of that type in the body for array element types (asm: `DYGR_ROUTE_ASM_NODE` 1,054,414; `unsigned short` 13,229,131; `DYGR_ROUTE_ASM_BIT` 29,159,476; all three match the parsed body exactly). 0 / small for struct types.
  - Names are Quartus C++ classes (`DYGR_*`, `DEV_*`, `std::string`).
- Body serialisation is per-type, field by field (not a memory image): `crosstalk` 120-byte struct = 3 x u32; strings = `u32 len` + bytes (no NUL); body starts with `u32 4` (format version).
- Exception: `ddb_cyclonev_info_counts.ddb` is `u64` (not the inflated size) + a raw zlib stream of an ASCII dump (part -> user name, NUM_OF_IO, ALUTs, ALMs, memory bits, DSP, PLL counts for 1,216+ parts).
- `device.db` (parent dir) is SQLite with base64-obfuscated names: `die`(`base_device_debug_name` = the die directory, display name = device family string, dsp_count, logic_resource_count), `part`, `part_resource`.

## Files per die (7 die directories, `cyclonev_<die>/`)

| file | content | e50f inflated |
|---|---|---|
| `*_hdr.ddb` (xz) | `DEV_BASIC_INFO_BODY`: device name `5CEFA4`, `Cyclone V`, `GENERIC`, `cyclonev50.mcf`, `.rba`, `.bvp`, clock-region file names, element/location descriptors | 286 KB |
| `*_asm.ddb` (zlib) | route assembler database: per routing SOURCE node, the select bits of every destination mux it feeds | 268 MB |
| `*_routing.ddb` (zlib) | routing graph / port tables (29 types: `DYGR_ROUTE_ELEMENT`, `DYGR_ROUTE_BLOCK_INTERFACE`, `DYGR_LOOKUP<...>`) | 40 MB; not decoded |
| `*_icname.ddb` (zlib) | `u32 4, u32 438588, u32 0x8001ccf8`, then 877,176 records `u32 len, name, u32 value` (readable wire names `H3R37C1RT[3]`, `LIM3R43C54`, `CLKLIMR21C52CS39RT[0]`); `value` semantics not resolved (1 for the first 438k, delta-like afterwards; not a permutation of node ids) | 18 MB |
| `*_place.ddb` (zlib) | `DYGR_PLACE_INFO_BODY`, clock regions, block types | 3.2 MB; not decoded |
| `*_pad.ddb`, `*_pkg.ddb`, `*_part_info.ddb`, `*.dmf.ddb`, `*_fdi.ddb`, `*_timing.ddb` | pads / packages / power / timing | not decoded |

## Die map (Quartus die dir -> devices; `cyclonev_ddb_decode.py diemap`)

- Option-RAM **die byte** = oram strip 6, bits 19..26, LSB first = low byte of the Mistral variant `idcode` (`cyclonev_decode.die_byte`). Verified on real Quartus `.rbf`: 0x05 in every e50f corpus build, 0x13 in the 5CEBA7 builds.
- The JTAG IDCODE itself is not stored in any `.ddb` (searched hdr/part_info/pad/device.db).
- Low byte alone is not unique across the SoC dies (0x01/0x02 occur for both `2bXX` and `2dXX`); the native decoder keeps a table only for the dies it has: `DEVICE_BY_DIE_BYTE`.

| die dir | hdr device | ALM | DSP | devices on the die | idcode16 (Mistral) |
|---|---|---|---|---|---|
| `cyclonev_gx25f` | 5CGXFC3 | 13,460 | 57 | 5CGXFC3, 5CGXBC3 | 2b01 |
| `cyclonev_e50f` | 5CEFA4 | 18,480 | 66 | 5CEFA2/A4 (E, F/B) | **2b05** (A4), 2b15 (A2) |
| `cyclonev_gt75f` | 5CGTFD5 | 29,080 | 150 | 5CGTFD5, 5CGXFC4/C5, 5CEFA5 | 2b02, 2b12, 2b22 |
| `cyclonev_d6_gtf150` | 5CGTFD7 | 56,480 | 156 | 5CGTFD7, 5CGXFC7, 5CEFA7/5CEBA7 | 2b03 (GT/GX), **2b13** (5CEFA7/5CEBA7) |
| `cyclonev_gt300f` | 5CGTFD9 | 113,560 | 342 | 5CGTFD9, 5CGXFC9, 5CEFA9 | 2b04, 2b14 |
| `cyclonev_sx50f` | 5CSXFC4 | 15,880 | 84 | 5CSXFC2/C4, 5CSEMA/BA 2/4 (HPS) | 2d01, 2d11 |
| `cyclonev_sx120f` | 5CSXFC6 | 41,910 | 112 | 5CSXFC5/C6, 5CSTFD5/6, 5CSEMA/BA 5/6 (HPS) | 2d02, 2d12 |

- **0x05 = e50f die, 5CEBA4/5CEFA4 (this repo's `5CEBA4U19C8`). 0x13 = `d6_gtf150` die, 5CEBA7/5CEFA7 (E150, 56,480 ALM = 4,310 LAB + 1,338 MLAB per the tables).** Geometry from the native tables: e50f CRAM 4958 x 3928, 55 x 46 tiles, frame 129 B; gt150f CRAM 7605 x 7024, 90 x 82 tiles, frame 227 B.

## asm.ddb body

- Body: `u32 4, u32 N, u32 N, u16 max_n, u16 max_nb` (e50f: N = 1,054,414; 42; 84), then records to EOF (a < 8-byte zero pad at the end; 1,054,413 full records + stub).
- Record: `u16 n`, `n x u16 vals`, `u16 nb`, `nb x (i32 delta, i32 flag)`, `i32 trailer`. `n = 0` -> 8 bytes (`0, 0, trailer`).
  - 109,641 empty records, 790,140 records with bits; records with `nb = 0` but `n > 0`: 154,632 (e.g. shape (1,0) 114,747).
  - Sums over the whole file equal the type table counts exactly (13,229,131 ushorts; 29,159,476 bits) and the parse ends exactly at EOF.
- **Position stream:** one running sum over the deltas of ALL records (empty records add nothing); the trailer is NOT added. Position `P` = sum mod (cram_sx x cram_sy), linear address `x + y * cram_sx` = the same address the native tables use (`fw + dx + dy * width`).
  - Evidence (e50f, 2026-10-26): all 29,159,476 positions land on CRAM positions the native tables claim as ROUTING muxes (0 on block-mux / inverter / forced-1 / unclaimed); the distinct asm positions are 6,072,456 = exactly the 6,072,456 routing positions of the native tables (every one referenced, none extra). A wrong stream would hit 31 % (routing) / 58 % (any class).
  - First 36,960 records (e50f, source type `LD`): consecutive records advance by (dx 0, dy +86) = one tile row; 44 per column; columns advance by +59 (clean geometry, no fitting).
- **Semantics:** a record = one routing **source** node; `vals[0]` is a flag-like value, the entries are grouped per fanout destination mux (first fanout 2 bits, then `vals[1:]` bits each for the simple shapes); each group is the select code (set bits) of the destination mux for this source. Mistral's table is destination-centred (`mux -> sources`); asm is the transpose.
- `vals[0]` = 1 on exactly 4,137 records (group starts), 0 on the other 940,635. `vals[1:]` histogram: 2 (11.0 M), 1 (0.54 M), 4 (0.36 M), 0, 10, 12, 11, 14, 15 ...
- `flag`: 0 for 29,052,300 of 29,159,476 entries; the rest are packed small values (256 x 53,462, 65280 x 53,470, 1, 255, 257, 65535). `trailer`: 966,287 zero; 588 distinct values, many look like packed i16 pairs (131073 = (1,2), -65537 = (-1,-1+...)). Meaning unresolved (flag may be a per-bit polarity/ordinal, trailer a tile-coordinate step); neither is needed for positions.
- Second record family: ~205k records (e50f) carry the ALL-bits-set code of one destination mux (one per mux of several types): an "off" state the Mistral tables have no slot for.
- All 7 dies parse exactly: sums of `n` and `nb` equal the type-table counts and the parse ends at EOF (e50f 1,054,413 records, gt150f 2,847,246, gt300f 5,226,472, gt75f 1,671,073, gx25f 829,861, sx120f 2,279,563, sx50f 1,090,687; each = N-1 full records + a < 8-byte stub).

## asm vs native routing tables (`scripts/cyclonev_ddb_asm.py compare --die e50f|gt150f`, 2026-10-26)

Native tables = Mistral-sourced (`scripts/cyclonev_native_tables.py`). Unit = (destination mux, select code) pair; "source consistency" = all groups of one asm record resolve to the same source node in the native tables.

| | e50f (0x05) | gt150f (0x13) |
|---|---|---|
| routing CRAM positions, native / asm / both | 6,072,456 / 6,072,456 / 6,072,456 | 17,012,500 / 17,012,500 / 17,012,500 |
| asm positions outside native routing muxes | 0 | 0 |
| native (mux, code) pairs | 13,558,676 | 38,152,920 |
| matched (same mux, same code) | 11,764,244 | 33,061,705 |
| wrong (code resolves to a source different from the record's) | 0 | 0 |
| missing (native has it, asm does not) | 1,794,432 | 5,091,215 |
| extra (asm has it, native does not) | 597,698 (all = the all-bits-set code) | 1,679,292 (all = all-bits-set) |
| extra, any other code | 0 | 0 |
| headline matched / (matched + missing + extra + wrong) | 83.1 % | 83.0 % |
| asm records with a native source / sources seen once each | 575,348 / 575,348 | 1,596,424 (2,440 records share a source) |

- Missing, by distance of the source tile to the die edge (e50f): 1,767,426 of 1,794,432 are sources in the outermost tile ring (that ring holds 2,544,767 native pairs, 69 % of them missing); the rest are HCLK/BCLK/SCLK/PMUX clock-network sources. gt150f: 4,993,851 of 5,091,215 in the ring. Reading: the native tables list edge wires (and clock-network sources) that the vendor database has no source record for; not checked against the vendor routing graph.
- Extra: one all-bits-set code per mux (H3 163,840; H6 267,988; GOUT 552,024; TD 371,076 ... on gt150f): a state the native tables lack; native decode of such a mux reports "unknown value".
- Per dest type results: `tmp/cyclonev_ddb/<die>_asm_compare.json` (regenerate with the command above; ~25 s e50f, ~2 min gt150f, < 4 GB).

## Not decoded

- `routing.ddb` graph body, `icname` value semantics (node id mapping), `place`, `pad`, `timing`.
- asm `flag`, `trailer`, `vals[0]` semantics; records beyond the simple 2-bit shapes are compared by position only (see the comparison rules in the status doc).
