# Clean pipeline on the third-party EP4CGX150 image (2026-10-30, #165)

`scripts/cycloneiv_clean_image.py IMAGE` (or env `PLURIBUS_DJI_IMAGE`); log `tmp/logs/cycloneiv_clean_image.log`, results `tmp/cycloneiv_clean/image.json`. Test: `tests/cycloneiv_clean/test_image.py` (skips without the image).

- Image is read only; the decompressed plane is a derived file in `tmp/`, removed at exit. No path, name, hash or extracted material in tracked text; counts only.
- No ground truth exists for this image. Every number below is a decode count or an impossibility check, not a correctness score.
- Ambiguous / unresolved items are counted as MISSING. Tracer rules as the gate (headline variant `vendor`, tracer.py docstring).

## Mapping to the plane

- Container: compressed Cyclone III/IV rbf stream (32 x 0xFF + sync + stream), decompressed by `scripts/cycloneiv_decompress.py` (byte-identical to `quartus_cpf` layout, docs/cycloneiv-bitstream.md).
- The decompressed file is in rbf layout (796-byte frames, 37 periphery frames, CRAM frames after): `plane.py` A4 / A5 (sof -> rbf cell tables, mirror blocks) apply as for Quartus-built rbf files.
- Sections: CRAM = frames 37.. (39,040,976 bits); CFF = periphery frames 1..36 (31,060 bits, 4 replicas); option = header frame 0 (8 lanes x 40 bits).

## Integrity

| Check | Count |
|---|---|
| Header CRC16 | OK |
| CRAM frame CRC16 | 6,154 / 6,154 pass; 0 further valid frames after the chain |
| Decompressed length | 4,928,127 bytes (EP4CGX150 size) |
| CFF primary-replica disagreements | 0 of 31,060 bits |
| Set CRAM bits | 2,158,860 |

## Decode (headline variant `vendor`)

| Item | Count |
|---|---|
| Programmed routing edges / used routing nodes / net roots | rerun pending (`vendor` rule) |
| LUTs with non-zero INIT | 89,280 of 149,760 LEs (59.6 %); 19 all-ones |
| LABs with a LUT | 7,077 of 9,360 |
| LUTs with carry-in flag set | 20,260 |
| LEs with a used LE_BUFFER output | 60,131 |
| FFs claimed (register-used decode) | 34,112; clock line chosen for 31,495; 2,617 MISSING (no line) |
| Register-clock roots | 4,960 distinct clock lines, each with exactly one root; 6 distinct root nets (all `CLKBUF_OUT`); 0 ambiguous |
| M9K | 6,022 programmed edges out of M4K_BUFFER in 542 tiles (M9K columns); 27 block-input edges, all in LAB columns (24 tiles) |
| MAC | 0 programmed edges at multiplier columns |
| IO sites | 456 in chain, 455 map to a package ball (1 VIO site has no pad) |
| IO site classes (`io_fields`) | used 84 (44 output, 31 input, 9 bidir / tri-state); unused-pin state 368 (weak pull-up 286; ground / unspecified 82 = the unbonded pads of F672); device-fixed pad 4; MISSING 0 (CFF data groups, E-R8) |
| IO fields on the 84 used | direction 84 decoded; pull-up / bus-hold / open-drain / drive: 84 default (OFF / default); slew 53 decoded (all fast, value 2), 31 n/a (input); registered input / output / OE: 84 decoded OFF (CRAM patterns); termination 40 none, 44 ambiguous (none or 50 ohm series: CFF-identical); standard 9 decoded (2.5 V), 75 ambiguous (44 outputs: 2.5 V or SSTL-2 Class I; 31 inputs: 2.5 V, 3.0 / 3.3 V LVTTL / LVCMOS, 3.0-V PCI) |
| Option bits | 14 of 320 differ from a Quartus-built reference (lanes 0, 1, 3); meaning not decoded: all MISSING |

- M9K mode / width / init, MAC mode / coefficients, PLL, transceiver: not decoded (MISSING). Block-input mux for M9K sits at a coordinate not mapped to the M9K column, so input edges are not attributed.
- IO field decode (docs/cycloneiv-clean-io.md, last section): a site is classified only when its joint IOST / strength / clamp groups equal a pair-build or unused-pin state exactly; otherwise MISSING with raw patterns. MISSING sites: 0 (the 6 earlier ones were frame-end check cells read as data, E-R8). Package: F672 (inferred, exact).
- Detailed per-site table: local `tmp/cycloneiv_clean/image_io_table.json` (not committed).

## Sanity statistics

| Check | Image | Quartus-built controls (rb_000..002, same tracer) |
|---|---|---|
| Impossible counts (LUT / FF > 149,760) | none | none |
| Fan-in conflicts, `vendor` (dst nodes with > 1 programmed driver) | rerun pending | 0 of 64,375 on rb_000..009 (`scripts/cycloneiv_clean_fanin.py`) |
| Undriven used nodes | rerun pending | rerun pending |
| Loops (SCC > 1 node) | rerun pending | rerun pending |

- Conflicts and undriven nodes are tracer faults (a node cannot have two drivers); the controls show the same rate on designs with known ground truth, so the image sits at the tracer's own error level, not above it.

## Old stack (labelled old, not an oracle; docs/cycloneiv-bitstream.md)

- Used LEs 89,283 (mask != 0 or LE-used bit), LUTs 89,283, FFs 25,835, active LABs 7,077.
- Clean count: LUTs 89,280, LABs 7,077 (equal), FFs 34,112 (register-used decode differs from the old lifter's FF trace).

## Explained-set-bit rate (ground-truth-free lift metric, #165 #169)

Script `scripts/cycloneiv_clean_setbits.py` (counts only; third-party image read from the environment, never named). Measured 2026-10-30, EP4CGX150, class sets from `cycloneiv_clean_classes.build`, plane cells set in frames 1.. (header excluded).
Tiers (a set cell is in exactly one): A = placed by a gate-scored class (LUT INIT, routing pips under the vendor rule, clock network, IO pair-measured); B = decoded, no oracle (clock select, register-used, IO sampled / decoded); C = address-only group (other LAB groups, M9K, MAC); D = no class, inside a column tile; E = no class, pre-column frames / IO bands / periphery.

| design | set cells | A | B | C | D | E | explained A+B+C | validated A | gate pips / LUT INIT |
|---|---|---|---|---|---|---|---|---|---|
| rb_000..009 (10 Quartus-built, ground truth) | 259,675..274,843 | 13,747..24,722 | 5,227..6,214 | 220,769..224,141 | 11,124 each | 8,778..8,829 | 92.32..92.76 % | 5.29..8.99 % | 99.53..99.82 % / 100 % |
| rb_010..019 (no gate rows) | 258,696..278,201 | 13,274..27,126 | 4,945..6,336 | 220,536..224,876 | 11,124 each | 8,775..8,844 | 92.29..92.84 % | 5.13..9.75 % | not scored |
| third-party image | 2,178,780 | 1,230,328 | 127,400 | 800,357 | 11,140 | 9,555 | 99.05 % | 56.47 % | not scored |

- Reading:
  - Corpus builds are small designs: C (address-only) is 85 % of their set bits and is nearly design-independent (220.5 k..224.9 k) = default / off-state bits of placed groups. Their explained rate (92.5 %) measures the background, not decoding.
  - D (11,124) is identical in all 20 corpus designs and 16 higher in the image: constant default-state cells (hard-block absolute groups and DEFAULT_BIT_CALC cells are placed by vendor records but not in these class sets). E = 8.8 k in the corpus, 9.6 k in the image (+0.8 k).
  - The image is where the metric separates: A = 56.5 % of its set bits, B 5.8 %, C 36.7 %, D+E 0.9 %.
- Calibration against truth (rb_000..009): the A tier's gate rates are pips 99.5..99.8 %, nets 95.8..98.3 %, LUT INIT 100 %, register-clock 99.1..100 %. So an A-tier set bit is placed by a decoder whose pip output is ~99.7 % right; "placed" is not "correct": gaps are missing pips (gate `missing` > 0), nets (pins 72 %), and any bit that a decoder places but the gate does not score (all of C, most of B).
  - Image estimate: validated-correct set bits ~ 56.5 % x ~0.997 = ~56 % (pips) with LUT INIT exact; the 36.7 % in C is placed, meaning unknown; the proxy cannot see decoded-but-wrong bits in tiers B and C.
- Limits: set-bit counts weight every bit equally (a routing mux spends 2-3 bits per pip, a LUT 16 bits); D / E are not the 12.5 M vendor-residue (that counts unset cells too).
