# Cyclone IV GX150 configuration-bit inventory

Tool: `scripts/cycloneiv_bit_inventory.py --image <path> --record` (run with `--record` after every checklist item: appends one line to `docs/coverage-history.jsonl`, the coverage-over-time ledger; read-only otherwise; log `tmp/logs/cycloneiv_bit_inventory.log`, JSON `tmp/cycloneiv_bit_inventory.json`). Issue #141.

## Method

- Universe = 6,191 frames x 6,368 bits (frame 0 header, 36 periphery, 6,154 CRAM) + 728 preamble/postamble bits = 39,425,016 bits (= handbook figure).
- Every cell gets ONE class, first match wins, order 1 -> 6. Claims lost to an earlier class are listed in the log (`claim overlaps`).
- Existing decoders only: `cycloneiv_geom` anchors + `cycloneiv_le_locate.DK` (cells), `tmp/cycloneiv_forced_lab*.json` (specimens), `cycloneiv_corpus.cram_plane` (image plane).
- Image = the third-party EP4CGX150 image, 2,178,780 set bits in the plane (+6,280 header, +52,338 CRC bytes, +728 pre/post = 2,238,126).
- Run 2026-10-29, interpreter `the free-threaded interpreter` (the default 3.15t env had no numpy at the time).

## Tiers (what "known" means here)

Names are the Glossary of provenance-and-feedback.md (one definition; this list restates it); each inventory class carries exactly one, COMPUTED from its `CLASS:<id>` claim and linked evidence rows by `provenance/tiering.py:class_verdict` (rule, n and misses printed per class; `claims_register.py` links the evidence, the inventory reads the verdict). Nothing sets a tier by hand; `tests/test_tiering.py` shows a refuting row flipping a class. Where the classes land today: 1a, 5b verified; 3, 4f, 4h, 5d measured; 4g sampled (112 sites) and 1c sampled (6 LABs), extremes included; 3t (4 LABs), 4i (3 sites) pattern-predicted (< 5 scopes for a 2-D law); 2a, 2b decoded; 1b suspect (conflict row). Patterns are revocable (recovery-process.md "Patterns and certainty"): a miss moves a class to suspect/refuted and its bits out of the verified tiers.

- **verified** = oracle-verified: compared claim-for-claim against a vendor oracle (1a, 5b, header sync/CRC).
- **measured** = raw diff or observation at that cell/site (3 at the 4 specimen LABs, 4f, constants).
- **sampled** (= verified-by-sampling) = a pattern confirmed at >= N distinct scopes incl. extremes, zero refutations (4g: 120 site checks, all 8 columns, 0 misses; 1c: 6 LABs).
- **pattern-predicted** = a rule fitted to measured parents, below the sampling bar (3t: ll-translate-v1, 4 LABs confirmed, 2-D law needs 5).
- **statistical** = last-resort fit/vote, unverified, its own tier (none today since 1c reached sampled).
- **decoded** (= decoded-untested) = read from the vendor decode, nothing tested at the cell (1d-a, 1d-d).
- **suspect / refuted** = a pattern with a recorded miss / contradicted by a specimen in scope (1b: 14 misses in 1,018 LEs).
- **unknown** (the headline) = nothing attributes a meaning. Sub-line, not subtracted: **of which projected unused (never set in n designs)** = triage by frequency, NOT a claim and never pattern-predicted: none of the n held GX150 bitstreams (corpus builds + GX150 third-party images + specimens; `scripts/cycloneiv_ever_set.py`, bitmap `databases/cycloneiv/ever_set.npy`) sets the cell. One design that sets the cell removes it from the sub-line. Other-device images (EP4CE) have another plane and are not counted. Ledger field `unknown_projected`.
- Ledger rows from before 2026-10-29 carry a single `evidence` bucket (unsplit); newer rows carry `verified, measured, sampled, predicted, statistical, decoded, suspect, refuted, unknown` (`statistical` absent = 0). Old rows are not migrated.

## (A) Die-wide TOTAL bits, (B) image SET bits

| id | class | tier | total bits | % die | image set |
|---|---|---|---|---|---|
| 1a | LUT INIT (16 bits x 16 LE x 9360 LAB) | verified | 2,396,160 | 6.08 | 649,507 |
| 1b | LE-used bit | suspect | 149,760 | 0.38 | 69,023 |
| 1c | LAB clock-polarity bit | sampled | 9,360 | 0.02 | 174 |
| 2a, 2b | removed 2026-10-30 (#165): asm routing attribution rode on the retired coordinate model (`docs/cycloneiv-retired-coordinate-model.md`); cells fall to the next class; returns with the clean address engine | | | | |
| 3 | LOCAL_LINE specimen bits at the 4 specimen LABs (measured) | measured | 1,156 | 0.00 | 36 |
| 3t | LOCAL_LINE specimen bits translated to all other LABs | predicted | 2,601,554 | 6.60 | 175,915 |
| 4a | periphery frames 1..36 (IO ring, clocks, PLL, misc) | unknown | 229,248 | 0.58 | 19,920 |
| 4b | M9K columns (8): cells outside the data tables and the control cells found | unknown | 7,876,924 | 19.98 | 91,171 |
| 4c | multiplier columns (4) | unknown | 620,960 | 1.58 | 22,433 |
| 4d | IOL / IOR columns (+ 4 frames before col 0) | unknown | 331,000 | 0.84 | 618 |
| 4e | IO row tiles (y=0, y=91) of LAB columns | unknown | 118,034 | 0.30 | 1,004 |
| 4f | M9K data cells at sites with an exact offset check | measured | 995,232 | 2.52 | 0 |
| 4g | M9K data cells at the other sites (per-site offset rule) | sampled | 5,402,688 | 13.70 | 12,387 |
| 4h | M9K control cells (knob pairs) at the sites where measured | measured | 18 | 0.00 | 7 |
| 4i | M9K control cells at the other sites (offset rule) | predicted | 4,302 | 0.01 | 1,802 |
| 5a | header frame 0 | mixed | 6,368 | 0.02 | 6,280 |
| 5b | CRAM frame CRC-16 bytes | verified | 98,464 | 0.25 | 52,338 |
| 5c | lane-tail byte (v 6344..6351, CRAM frames) | unknown | 49,227 | 0.12 | 1,915 |
| 5d | preamble + postamble (0xFF fill, outside frames) | measured | 728 | 0.00 | 728 |
| 6 | unclassified (LAB-column cells no decoder claims) | unknown | 11,188,995 | 28.38 | 601,552 |

- Die-wide, ledger row 2026-10-29T15:33 (+11:00), 3,448 held GX150 bitstreams: verified 2,494,648 (6.33 %); measured 1,003,319 (2.54 %); sampled 5,412,048 (13.73 %); pattern-predicted 2,605,856 (6.61 %); statistical 0; decoded 7,344,838 (18.63 %); suspect 149,760 (0.38 %); refuted 0; unknown 20,414,547 (51.78 %), of which projected unused 18,569,054 (47.10 %). Class table with basis and sample n: `reports/coverage.html` section 5 and the inventory log.
  - Header split used: 24 bits verified (sync + CRC-16), 6,185 known/constant (flag, length, family, lanes 5-7, 0xFF fill), 159 option bits unknown (docs/cycloneiv-bitstream.md "Format").
- Image set bits: verified-class 701,845 (31.4 %); other-evidence 776,464 (34.7 %); unknown-class 752,809 (33.6 %); header/pre/post 7,008.
- Not in the partition: 1,506,513 asm entries (261,850 distinct asm bits) have no plane cell (outside every column band). Placed asm cells: 7,359,058 of 51.6 M entries.

## Verification per class

- 1a: LUT mask vs post-fit `.vo` lut_mask, 301 designs, 5,354,496 bits, matched 100 %, missing 0, wrong 0 (`cycloneiv_lut_check.py`, docs/cycloneiv-bitstream.md). Oracle = Quartus post-fit netlist, GX150 corpus builds.
- 1b: "set for 95.8 % of LUT cells"; 14 of 1,018 LEs on one design missed. Partial.
  - Specimen cross-check: the 16 per-LAB "source-LE" bits of the LOCAL_LINE specimens coincide exactly with the 1b positions (149,760 / 149,760 cells). The bit flips when the LE output gets a fanout.
- 1c: greedy fit, Jaccard 0.85 over 5,442 clock lines, plus isolated polarity cells (bit hunter, calibration) at 6 LABs: `sampled`.
- 2a / 2b: removed (see table); history lines in `docs/coverage-history.jsonl` keep them.
- 3 / 3t: raw-diff specimens, 240 (src, snk) pairs each in LABs X10Y10, X58Y30, X37Y60, X100Y75 (3 = those LABs, measured; 3t = translated to all others, pattern-predicted).
  - Translation rule (frame = FX[x] + rel, v = 20 + 70 y + rel) reproduces the X10Y10 pattern in 240 / 240 pairs at each of the other 3 LABs (X37 is the column right after an M9K column).
  - Applied to all 9,360 LABs: edge rows y1 / y90 and edge-adjacent columns are NOT verified by a specimen.
  - 305 cells per LAB: 32 source-LE bits (2 per src LE; one is the 1b bit, the other sits at FX+2), 227 pair-unique bits (sink input-mux select for one src), 46 sink-shared bits (one sink, 8 src).
  - Meaning known at "bit set iff this hop is routed" level only. Ports covered: DATAC, DATAD.
  - Image full 4-bit matches: 19,240 (LAB, pair) in 3,658 LABs. Per (LAB, sink): 1 matching src 13,296, 2 srcs 2,972. This is a necessary-not-sufficient test (no exclusivity).
  - 250,465 image set bits lie in the translated specimen cell universe (175,951 left in class 3 after 1b took theirs (measured with 2a / 2b present)).
- 5b: CRC-16 recomputed per CRAM frame by `cycloneiv_decompress` (70 / 70 vendor pairs). Verified as a checksum, not a config meaning.
- 5c is NOT padding: 1,915 set in the image (LAB 1,557, M9K 318, MUL 39). Lane-tail cells sit just above the y91 band; treat with the IO-row work.
- 4a-4e: located by column/frame geometry only (`col_kind` + FX-19 band start + row band [VY-68, VY+1], approximate). No decoder. IO-pin signatures in `cycloneiv_io_bits.py` are statistical and not counted.
- 6: nothing claims these cells. 601,552 are set in this image (the largest set-and-unknown pool).

## Unknown regions (one partition of 4a-4e, 5c, 6; unknown bits, set in image)

| # | region | unknown | % die | set | next specimen (smallest, raw diff; bit counts are the 2026-10-29 14:18 run) |
|---|---|---|---|---|---|
| 1 | M9K columns (8), cells outside data tables + control cells found (4b) | 7,876,924 | 20.0 | 91,171 | M9K ports checklist (docs/cycloneiv-specimens.md): one port pin, one far end per build; data tables and widths are done (4f, 4g) |
| 2 | LAB core FX-19..FX-8 (435 / tile) | 4,072,150 | 10.3 | 246,472 | LE modes (normal vs arithmetic, `sum_lutc_input`) and packing flags via `cycloneiv_lab_modes.py`; sink ports DATAA-D are done |
| 3 | LAB core control stripe, v phase 31..39 (258 / tile) | 2,410,896 | 6.1 | 104,298 | `cycloneiv_ctrl.py` pos / pos2 / idle sets (clk, ena, aclr, sclr, sload, asdata done) |
| 4 | LAB core FX-7..FX+0 (230 / tile) | 2,155,692 | 5.5 | 0 | one LE, same lut_mask: normal vs arithmetic; then LE with FF vs without |
| 5 | LAB core FX+1..FX+3 (159 / tile) | 1,491,673 | 3.8 | 205,599 | LE_BUFFER fan-out: LUT -> FF vs LUT -> LI, one group per pair |
| 6 | LAB core FX+4..FX+13 (103 / tile) | 959,744 | 2.4 | 39,671 | forced C4 hop per pair, base = sink pin open (script retired, tag `pre-clean-cycloneiv`) |
| 7 | multiplier columns (4) | 620,960 | 1.6 | 22,433 | one 9x9 multiplier, LOCATION pinned: input register off vs on (one parameter) |
| 8 | IOL / IOR columns | 331,000 | 0.8 | 618 | one pin in IOR column: unused vs LVTTL input; then one pin as output |
| 9 | periphery frames 1..36 | 229,248 | 0.6 | 19,920 | one top-row IOIBUF: unused vs used (same pin), then I/O standard changed (one param) |
| 10 | LAB columns IO rows y0 / y91 | 118,034 | 0.3 | 1,004 | one bonded pin per IO row tile: pin as input vs unused (matrix row 6 / 7, Tier 0) |
| - | lane-tail byte (5c) | 49,227 | 0.1 | 1,915 | read from the y91 IO-pin specimen diff above |

- Rows sorted by unknown bits for reading only; the work queue is the gate per-hop table (recovery-process.md Priority order). Set counts are for this image only; cells never set here may be set elsewhere.
- Rows 2-6 are all of the class-6 LAB-column cells: per-frame-offset profile is in the JSON (`class6_by_offset`); offsets FX+4..FX+13 are mostly claimed by asm (44 k-92 k per offset), the others hold 330-630 k each.
- Specimen rules apply (docs/recovery-process.md): base + specimen differ in one thing, raw diff only, report before scaling.

## Findings

- Queue order is the priority rule in docs/recovery-process.md: what gates the lift first (latest gate per-hop table), die coverage % ranks only gate-neutral classes; checklists in docs/cycloneiv-specimens.md.
- M9K bands are 36 % of the die and gate-neutral today: they rank by bits only among gate-neutral classes, below any gate-touching wire class.
- Class 6 (28 % of the die, 601 k image set bits) is LAB-column cells with no asm entry, no LUT / used bit, no specimen: the control stripe and the LUT-frame remainder are the biggest pieces.
- Verified coverage is 6.3 % of the die and 31.4 % of the image's set bits (almost all LUT INIT); routing bits are decoded but unverified.
