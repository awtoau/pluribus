# Die map with one image's known cells + zero/one encoding (issue #141)

Tool: `scripts/geo_image_overlay.py --image <image>` (one run ~25 s, peak ~4 GB). Log `tmp/logs/geo_image_overlay.log`. Outputs in `tmp/geo/` (not committed): `image_tiles.csv` (per tile, all 15 classes), `image_tiles.geojson`, `image_encoding.json` (every number below), the explorer cache `image_overlay_data.json`; the page is `tmp/geo/explorer.html` (`scripts/geo_explorer.py`, `docs/geo-explorer.md`).
Image = the third-party EP4CGX150 image (2,238,126 set bits incl. header/CRC/pre-post). Measured 2026-10-29. Other images: 5 GX150 corpus images (class layout shared) and 11 other-die corpus images (frame level only).

## Method

- Class per cell = `cycloneiv_bit_inventory` classes 1a..6 (same claim order; per-class cell and set counts reproduce the inventory exactly).
- Tiers for tile accounting: verified = 1a; evidence = 1b, 1c, 2a, 2b, 3; unknown = 4a-4e, 5c, 6; overhead = 5b (CRC bytes, excluded from the known fraction). "Known" = verified + evidence.
- Owner tile per cell (exact where the generator is known):
  - 1a/1b/1c/3: the LAB that generated the cell.
  - 2a/2b: column whose FX is the largest <= frame (asm band FX..FX+17); row from v.
  - 4*/5c/6/5b: frame band `FX-19..` per column, v row band `[70y-48, 70y+21]` (= VY-68..VY+1, VY = 20 + 70y).
- Tile rectangle drawn in the page = exact extent of frames holding cells the column owns (LAB 37 frames normally; 41 where a column pair has a 4-frame gap; M9K ~293; MUL 25+).
- Capacity per tile (die-wide, image independent) = cells of 1a (verified) and 1b, 1c, 2a+2b, 3 (evidence).
- Explorer payload: the class map per tile is deduplicated (68 templates), set bits are packed per tile and deflated (1.27 MB); decoded in the browser with `DecompressionStream`.

## Approximations that remain

- v row band: asm cells and unclaimed cells (class 6, 4*) are binned by the 70-v band; a different phase would move cells between vertically adjacent tiles. The LE and specimen cells fit the band exactly (0 cells outside).
- Frames FX+16..FX+17 of a LAB column overlap the next column's FX-19..FX-18. Asm cells there go to the left column; class-6 cells there go to the right column (no evidence which is right).
- MUL columns are 25 frames wide but their asm table band is FX..FX+17 from an implied anchor: 59,016 table-only cells per MUL column (2a/2b) overlap the next LAB column's frames; owned by the MUL tile per the table. Treat MUL "evidence" set bits (12,873) as table claims, not measured meanings.
- 2b (table-only routing) and 3 (specimen translated to every LAB, edge rows/columns not specimen-verified) count as "known" in the evidence tier: weaker than verified.
- Periphery frames 1..36 (229,248 cells, 19,920 set) and the header frame (6,280 set) belong to no tile; reported separately.

## Overlay findings (this image)

- Set bits in tiles: verified 649,507; evidence 776,464; unknown 732,889; CRC bytes 52,338. Periphery 19,920 + header 6,280 outside tiles.
- Known share of set bits by tile kind: LAB 70.1 % (2,013,575 set); IOL 83.8 %; MUL 36.4 %; M9K 0.4 % (127,961 set, 105,685 unknown); IO rows (y0/y91 of LAB columns) 4.0 %; IOR 0 %.
- LAB tiles: median known share 69 %; 517 of 9,360 have set bits and zero known; 1,505 tiles die-wide (mostly M9K, IO ring) have set bits and none known.
- Largest unknown pools by set bits: class 6 in LABs 601,552 (control stripe, FX-19..FX-8 and FX+1..FX+3); M9K columns 105,685 (columns X36, X7, X94, X52, X65, X81, X23 each 12-17 k); MUL 22,472; periphery 19,920.
- Largest single unknown tiles: M9K X7 Y57 (4,765), X94 Y57 (2,080), X36 Y64 (1,697).
- Capacity (cells with a proposed meaning regardless of image): LAB 11.65 M of 22.84 M cells; M9K 0.50 M of 14.83 M; MUL 0.25 M of 0.87 M.

## Encoding: is "nothing" 0?

Verdict: yes, with a few constant-1 exceptions. Idle = 0 for LUT contents, routing selects, memory/multiplier content and almost all unknown cells.

Measured:
- Overall set fraction: 5.66 % of plane cells (2,231,118 / 39,417,920); 5.68 % of the die incl. header/CRC/pre-post. Other GX150 images 0.71-1.49 %; all 16 corpus images 0.7-9.6 % of CRAM data bits.
- No CRAM frame has more than 50 % set bits: max 31.3 % in this image, 24-26 % in the other GX150 images, 24-35 % in the other corpus images. Median frame 4.6 %.
- Per class set fraction: 1a 27.1 %, 1b 46.1 %, 1c 1.9 %, 2a 44.9 % (fired groups), 2b 0.68 %, 3 6.8 %, 4a 8.7 %, 4b 0.74 %, 4c 3.6 %, 4d 0.19 %, 4e 0.85 %, 5c 3.9 %, 6 5.4 %.

Regions where 1 is the idle value (> 50 % set), all explained:
- Header frame 98.6 % (6,280 / 6,368): 0xFF fill + constant lanes. Other dies 94.8-98.8 %.
- Preamble + postamble 100 % (0xFF, 728 bits).
- CRC-16 bytes 53 % (44-59 % across images): checksum of the frame, not config. The 6-image-wide "always set" CRC cells (16,010) are CRCs of identical (mostly empty) frames.
- LAB constant ones: 17 cells at frame FX+3 (v rows 4, 5, 12, 13, 20, 21, 28, 29, 37, 42, 43, 50, 51, 58, 59, 66, 67) set in 100 % of LABs, idle or busy; cell FX+0 row 36 99.6 %. All class 6 (unknown).
- LAB control-stripe cells that are 1 when idle: (FX-7, row 33), (FX-7, row 38), (FX+1, row 36) are set in 100 % of the 635 idle LABs and 49-67 % of busy ones; (FX+0, row 36) 100 % / 99.6 %, (FX+2, row 36) 100 % / 93 %. Idle = 1 for these, so a used control clears or toggles them (polarity inverted). Meaning unknown.
- M9K: 24 cells set in > 90 % of the 720 M9K tiles (17,137 set bits); MUL: 1 cell in all 360 tiles. No M9K or MUL tile has zero set bits (min 30 and 1).
- Periphery frames: 16,136 cells set in all 6 GX150 images; 247,665 cells die-wide set in all 6 images (class 6 186,441; 4b 19,262; 2a/2b 8,052; 5b 16,010).

(b) Unused logic:
- Idle LAB (LE-used bits 0, clock bit 0, no fired-group cell set) = 635 of 9,360 LABs. In them: LUT INIT cells 88 / 162,560 set (0.05 %); routing table cells 2b 264 / 386,613 (0.07 %); specimen cells 1 / 178,418; class 6 14,141 / 806,522 (1.75 %), of which 13,970 are the constant-1 cells above. Everything else = 0.
- LEs with LE-used bit 0: 80,737; 60,477 have INIT = 0000, 0 have INIT = FFFF, 20,260 have a non-zero INIT (LE-used bit is the LI-fanout bit, not "LE unused"). LEs with the bit set: INIT 0000 in 3, FFFF in 19 of 69,023.
- LUT INIT polarity: INIT bit 1 = cell 1 (verified, 100 % vs vendor netlists, #141).

(d) Routing muxes (asm blocks; unit = mux):
- 2,510,160 blocks have placed cells: 1,842,568 (73.4 %) all-zero, 667,592 some set; 352,405 fire exactly one group; 3,554 have every cell set.
- Groups: 17,291,291; 1,748,178 (10.1 %) have an empty programmed pattern (only shared second-level bits, none programmed); 1,323,170 blocks have exactly one such group, 11,176 have two or more.
- All-zero rate is the same with and without an empty-pattern group: 73.0 % (967,615 / 1,324,631) vs 73.8 % (874,953 / 1,185,529). So all-zero is the idle state of unused muxes in both kinds.
- Verified from specimens (evidence rows, `provenance`): 2,497 specimen pairs (LOCAL_LINE, LE-output, tier, M9K) set only cells: cells 1 -> 0 = 0 in every pair (base minus net, spec adds the select cells; "not connected" = 0 in all of them).
- Inferred, not verified: whether all-zero in a mux that has an empty-pattern group also selects a default input. The data cannot separate it from "nothing selected" (no specimen lights a default input).

(e) M9K and multiplier:
- M9K tiles (720): set bits per tile min 30, quartiles 85 / 118 / 155, max 4,982; 20,384 cells per tile. Lowest quartile (180 tiles, <= 85 set): 26 cells set in > 90 % of them, 65 set bits per tile on average. So an unused M9K is not all-zero: it holds a fixed pattern (~24-26 ones), cause unknown.
- MUL tiles (360): 1..243 set; 1 constant cell.
- M9K content polarity (verified, specimens `m9k_p0`, `m9k_data1d`, `m9k_bincode*`, `m9k_rand*`): init 0 = cell 0; word/bit set to 1 sets exactly one cell (141 data-pair specimens, 141 cells 0 -> 1, 0 cells 1 -> 0).

## Verified vs inferred

- Verified by measurement on images: overall/per-class set fractions; no frame > 50 %; header/CRC/pre-post polarity; constant-1 cell lists; idle-LAB composition; block statistics; M9K/MUL tile statistics.
- Verified by vendor oracle: LUT INIT polarity (class 1a).
- Evidence rows: "not connected" = 0 in all specimen pairs (0 of 2,497 pairs clear a cell).
- Inferred: meaning of the constant-1 LAB cells and the 1-when-idle stripe cells (control polarity); meaning of the M9K constant pattern; whether all-zero selects a default mux input; MUL asm-table placement.
