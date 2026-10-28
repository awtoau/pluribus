# Cyclone IV GX150 configuration-bit inventory

Tool: `scripts/cycloneiv_bit_inventory.py --image <path> --record` (run with `--record` after every checklist item: appends one line to `docs/coverage-history.jsonl`, the coverage-over-time ledger; read-only otherwise; log `tmp/logs/cycloneiv_bit_inventory.log`, JSON `tmp/cycloneiv_bit_inventory.json`). Issue #141.

## Method

- Universe = 6,191 frames x 6,368 bits (frame 0 header, 36 periphery, 6,154 CRAM) + 728 preamble/postamble bits = 39,425,016 bits (= handbook figure).
- Every cell gets ONE class, first match wins, order 1 -> 6. Claims lost to an earlier class are listed in the log (`claim overlaps`).
- Existing decoders only: `cycloneiv_geom` anchors + `cycloneiv_le_locate.DK` (cells), `cycloneiv_asm_decode.Dec.active` (routing), `tmp/cycloneiv_forced_lab*.json` (specimens), `cycloneiv_corpus.cram_plane` (image plane).
- Image = the third-party EP4CGX150 image, 2,178,780 set bits in the plane (+6,280 header, +52,338 CRC bytes, +728 pre/post = 2,238,126).
- Run 2026-10-29, interpreter `the free-threaded interpreter` (the default 3.15t env had no numpy at the time).

## Evidence tiers (what "known" means here)

- **verified** = compared against a vendor oracle.
- **decoded / partial / specimen / table-only** = a mapping exists, no per-bit oracle compare. NOT counted as verified.
- **unknown** = nothing attributes a meaning.

## (A) Die-wide TOTAL bits, (B) image SET bits

| id | class | tier | total bits | % die | image set |
|---|---|---|---|---|---|
| 1a | LUT INIT (16 x 16 LE x 9,360 LAB) | verified | 2,396,160 | 6.08 | 649,507 |
| 1b | LE-used bit (1 per LE) | partial | 149,760 | 0.38 | 69,023 |
| 1c | LAB clock-polarity bit | partial | 9,360 | 0.02 | 174 |
| 2a | asm cells of groups fired in this image | decoded | 1,088,699 | 2.76 | 488,484 |
| 2b | asm cells, groups/blocks not fired in this image | table-only | 6,256,139 | 15.87 | 42,832 |
| 3 | LOCAL_LINE specimen bits (translated to all LABs) | specimen | 2,602,710 | 6.60 | 175,951 |
| 4a | periphery frames 1..36 | unknown | 229,248 | 0.58 | 19,920 |
| 4b | M9K columns (8), whole band | unknown | 14,279,164 | 36.22 | 105,367 |
| 4c | multiplier columns (4) | unknown | 620,960 | 1.58 | 22,433 |
| 4d | IOL / IOR columns (+4 pre-col frames) | unknown | 331,000 | 0.84 | 618 |
| 4e | IO rows y0 / y91 of LAB columns | unknown | 118,034 | 0.30 | 1,004 |
| 5a | header frame 0 | mixed | 6,368 | 0.02 | 6,280 |
| 5b | CRAM frame CRC-16 bytes | verified | 98,464 | 0.25 | 52,338 |
| 5c | lane-tail byte v 6344..6351 | unknown | 49,227 | 0.12 | 1,915 |
| 5d | preamble + postamble | constant | 728 | 0.00 | 728 |
| 6 | unclassified, LAB-column cells | unknown | 11,188,995 | 28.38 | 601,552 |

- Die-wide: verified 2,494,648 (6.33 %); other evidence (1b, 1c, 2a, 2b, 3, constants) 10,113,581 (25.65 %); unknown 26,816,787 (68.02 %).
  - Header split used: 24 bits verified (sync + CRC-16), 6,185 known/constant (flag, length, family, lanes 5-7, 0xFF fill), 159 option bits unknown (docs/cycloneiv-bitstream.md "Format").
- Image set bits: verified-class 701,845 (31.4 %); other-evidence 776,464 (34.7 %); unknown-class 752,809 (33.6 %); header/pre/post 7,008.
- Not in the partition: 1,506,513 asm entries (261,850 distinct asm bits) have no plane cell (outside every column band). Placed asm cells: 7,359,058 of 51.6 M entries.

## Verification per class

- 1a: LUT mask vs post-fit `.vo` lut_mask, 301 designs, 5,354,496 bits, matched 100 %, missing 0, wrong 0 (`cycloneiv_lut_check.py`, docs/cycloneiv-bitstream.md). Oracle = Quartus post-fit netlist, GX150 corpus builds.
- 1b: "set for 95.8 % of LUT cells"; 14 of 1,018 LEs on one design missed. Partial.
  - Specimen cross-check: the 16 per-LAB "source-LE" bits of the LOCAL_LINE specimens coincide exactly with the 1b positions (149,760 / 149,760 cells). The bit flips when the LE output gets a fanout.
- 1c: greedy fit, Jaccard 0.85 over 5,442 clock lines. Partial.
- 2a: asm.ddb tables are vendor data, but the (frame, v) map is inferred (per-column asm bases come from vote peaks; 83 % of learner patterns land in one group). Held-out routing score of the asm decode alone: 17.1 % of pips (docs/cycloneiv-bitstream.md). No per-bit oracle compare.
  - Fired = predicted bits all set AND block exclusive: 352,405 groups of 17.3 M. 32 columns have an asm base != plane FX (20 are LAB columns: 6, 12, 13, 22, 28, 29, 35, 41, 42, 51, 64, 72, 73, 80, 86, 87, 93, 101, 102, 109).
- 2b: same tables; this image does not fire them. Meaning of a cell exists on paper (which mux input), unverified.
  - 42,832 image set bits sit in 2b cells: routing bits the decode cannot attribute (exclusivity or pseudo-group).
- 3: raw-diff specimens, 240 (src, snk) pairs each in LABs X10Y10, X58Y30, X37Y60, X100Y75.
  - Translation rule (frame = FX[x] + rel, v = 20 + 70 y + rel) reproduces the X10Y10 pattern in 240 / 240 pairs at each of the other 3 LABs (X37 is the column right after an M9K column).
  - Applied to all 9,360 LABs: edge rows y1 / y90 and edge-adjacent columns are NOT verified by a specimen.
  - 305 cells per LAB: 32 source-LE bits (2 per src LE; one is the 1b bit, the other sits at FX+2), 227 pair-unique bits (sink input-mux select for one src), 46 sink-shared bits (one sink, 8 src).
  - Meaning known at "bit set iff this hop is routed" level only. Ports covered: DATAC, DATAD.
  - Image full 4-bit matches: 19,240 (LAB, pair) in 3,658 LABs. Per (LAB, sink): 1 matching src 13,296, 2 srcs 2,972. This is a necessary-not-sufficient test (no exclusivity).
  - 250,465 image set bits lie in the translated specimen cell universe (175,951 left in class 3 after 1b / 2a / 2b took theirs).
- 5b: CRC-16 recomputed per CRAM frame by `cycloneiv_decompress` (70 / 70 vendor pairs). Verified as a checksum, not a config meaning.
- 5c is NOT padding: 1,915 set in the image (LAB 1,557, M9K 318, MUL 39). Lane-tail cells sit just above the y91 band; treat with the IO-row work.
- 4a-4e: located by column/frame geometry only (`col_kind` + FX-19 band start + row band [VY-68, VY+1], approximate). No decoder. IO-pin signatures in `cycloneiv_io_bits.py` are statistical and not counted.
- 6: nothing claims these cells. 601,552 are set in this image (the largest set-and-unknown pool).

## Unknown regions (one partition of 4a-4e, 5c, 6; unknown bits, set in image)

| # | region | unknown | % die | set | next specimen (smallest, raw diff) |
|---|---|---|---|---|---|
| 1 | M9K columns (8), all rows | 14,279,164 | 36.2 | 105,367 | one M9K (altsyncram 1b x 8192w), LOCATION pinned: all-zero init vs word 0 bit 0 = 1 -> expect 1 cell; then word 1, 2, 4, 8... for the address law |
| 2 | LAB core FX-19..FX-8 (435 / tile) | 4,072,150 | 10.3 | 246,472 | extend the LOCAL_LINE grid to sink ports DATAA / DATAB in one LAB (same pair design, one port changed) |
| 3 | LAB core control stripe, v phase 31..39 (258 / tile) | 2,410,896 | 6.1 | 104,298 | 2 FFs in one LAB, clock from pin: base vs + ENA from a 2nd pin; then ACLR; then SCLR; one control per pair |
| 4 | LAB core FX-7..FX+0 (230 / tile) | 2,155,692 | 5.5 | 0 | one LE, same lut_mask: normal vs arithmetic (`sum_lutc_input` cin); then LE with FF vs without |
| 5 | LAB core FX+1..FX+3 (159 / tile) | 1,491,673 | 3.8 | 205,599 | matrix row 3: LUT -> FF vs LUT -> LI, one LE_BUFFER fan-out group per pair |
| 6 | LAB core FX+4..FX+13 (103 / tile) | 959,744 | 2.4 | 39,671 | matrix row 4: one forced C4 hop (4 columns right) per pair, base = sink pin open |
| 7 | multiplier columns (4) | 620,960 | 1.6 | 22,433 | one 9x9 multiplier, LOCATION pinned: input register off vs on (one parameter) |
| 8 | IOL / IOR columns | 331,000 | 0.8 | 618 | one pin in IOR column: unused vs LVTTL input; then one pin as output |
| 9 | periphery frames 1..36 | 229,248 | 0.6 | 19,920 | one top-row IOIBUF: unused vs used (same pin), then I/O standard changed (one param) |
| 10 | LAB columns IO rows y0 / y91 | 118,034 | 0.3 | 1,004 | one bonded pin per IO row tile: pin as input vs unused (matrix row 6 / 7, Tier 0) |
| - | lane-tail byte (5c) | 49,227 | 0.1 | 1,915 | read from the y91 IO-pin specimen diff above |

- Ranking is by unknown bits. Set counts are for this image only; cells never set here may be set elsewhere.
- Rows 2-6 are all of the class-6 LAB-column cells: per-frame-offset profile is in the JSON (`class6_by_offset`); offsets FX+4..FX+13 are mostly claimed by asm (44 k-92 k per offset), the others hold 330-630 k each.
- Specimen rules apply (docs/recovery-process.md): base + specimen differ in one thing, raw diff only, report before scaling.

## Findings

- Queue order is the priority rule in docs/recovery-process.md (die coverage %, big/regular first,
  edges last); the M9K checklist is in docs/cycloneiv-specimens.md.
- M9K bands are 36 % of the die; any M9K content/mode specimen outranks everything else by bits.
- Class 6 (28 % of the die, 601 k image set bits) is LAB-column cells with no asm entry, no LUT / used bit, no specimen: the control stripe and the LUT-frame remainder are the biggest pieces.
- Verified coverage is 6.3 % of the die and 31.4 % of the image's set bits (almost all LUT INIT); routing bits are decoded but unverified.
