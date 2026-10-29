# Cyclone V — vendor-shipped data and what we have read from it

Facts about files Quartus Prime Lite 25.1std ships for Cyclone V, and what we know about their layout. Method and status live elsewhere: [cyclonev-ddb-format.md](cyclonev-ddb-format.md), [cyclonev-rcf-oracle.md](cyclonev-rcf-oracle.md), [cyclonev-postfit-oracle.md](cyclonev-postfit-oracle.md), [cyclonev-status.md](cyclonev-status.md). Tags: **[V]** read/run, **[I]** inferred.

## `*_mtm_cff_mapping.csv.enc` (read 2026-10-29)

- Location: `quartus/common/devinfo/cyclonev/<die>/zb8_mtm_cff_mapping.csv.enc` and `zb16_...`; 7 die directories (d6_gtf150, e50f, gt300f, gt75f, gx25f, sx120f, sx50f) [V]. None exist for Cyclone IV (`cycloneive`, `cycloneivgx`) [V].
- NOT encrypted despite the extension [V]: 8-byte header `ac0f010000000000`, then a plain zlib stream (`78 9c`). `zlib.decompress(data[8:])` gives UTF-8 CSV (BOM). No key, no Quartus code.
- Same bytes in every die: the `zb16` file has one SHA-256 across all 7 dirs; compressed sizes are 88,943 (`zb8`) and 123,386 (`zb16`) everywhere [V]. Decompressed: 648,895 and 769,689 bytes; 10,366 and 13,731 lines [V].
- Columns (row 2): `$CFF, BINDEX, BROW, BCOL, BIT_SEQ, BIT_NAME`, then a second block with the same columns (sheet header `Pin Functions`, `MTM1` / `MTM2`); `zb8` adds `IO module index` and `QC Verify` columns [V]. Line 1 names the source sheet (`ZB8 (z1485a/rba/post_processed_rba/...)` — an internal chip code) [V].
- `zb16` content: 13,729 data rows [V]. `$CFF` name prefixes: DDR 8,816, LVDS 3,344, P (PLL) 1,392, DUMMY 64, VR 43, ADC 38, OCT 30, OSC 2 [V]. BROW 0..29, BCOL 0..50 [V]: a 30 x 51 grid of named bits.
- Reading [I]: a named-bit map for the hard-IP periphery (DDR/LVDS/PLL/OCT/ADC/VR/OSC): configuration field name, bit index, row/column on a small frame grid, bit name and owning block (`BIT_NAME` + block, e.g. `CR_LOCK1` in `PLL_CORE`). Not the core fabric. Relation of `BROW/BCOL` to `.rbf` positions is untested.
- Use: a ready source of periphery bit names and positions for Cyclone V; checks against the CRAM layout in [cyclonev-native-decoder.md](cyclonev-native-decoder.md) are open.
- Raw decompressed copies are kept locally in `vendor-analysis/altera/analysis/enc/` (gitignored); do not commit them.

## Device `.ddb` files

- Routing, asm, icname, place, timing: see [cyclonev-ddb-format.md](cyclonev-ddb-format.md) and the sizes/decompression notes in [fpga-map-tools-survey.md](fpga-map-tools-survey.md) (zlib after a 0x73-byte header; `asmdb`/`asmdb_dirt` use a different layout) [V].

## Routing oracle

- `quartus_cdb <proj> -c <rev> --back_annotate=routing` writes `<rev>.rcf`: every net's full routing tree in `TYPE:XxYyS<n>I<idx>` names. Used as the oracle for Cyclone V and Cyclone IV: [cyclonev-rcf-oracle.md](cyclonev-rcf-oracle.md) [V].

## Mistral (Ravenslofty/mistral, Cyclone V)

- Cyclone V only; README states it works "without having to look inside quartus" (black-box Quartus builds + `.rbf` diffing) [V].
- Ships per-die routing data `data/<die>-r.txt.xz`, a text format of routing muxes; docs describe the 2D CRAM layout and a `pos2bit` offset method per tile type (`cyclonev_library_internals.rst`) [V]. How the routing data was produced is not documented [V].
- No Quartus-internals documentation in the repo; maintainer states Cyclone IV compatibility "not even slightly" (issue #20) [V].

## Quartus assembler lookup path (static analysis; Cyclone IV GX libraries)

- Done on Cyclone IV GX (stingray) libraries; the same libraries (`libcomp_asm*`, `libddb_dygr`) are generic, so Cyclone V likely follows the same path [I].
- The assembler turns a routed edge into bits by exact lookup keyed (source element id, destination element id): group = destination's position in the source's fan-out list; each group bit is a flat address (31 bits, CFF flag selects another space), written as byte = address >> 3, bit = address & 7. No per-source base in this path. Decision and rules: issue #165.

## Open

- Parse the Cyclone V CSVs into a table and compare with the CRAM/RBF layout and with the DB's periphery bits.
- Cyclone IV has no counterpart file; candidates are the undecoded `hdr`, `asmdb`, `asmdb_dirt`, `place`, `pad` ddb files and the plain-text `.pll` file.
