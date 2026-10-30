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
| IO sites | 456 in chain; 170 with set key bits; 84 classified by default pattern (44 output, 31 input, 9 bidir); 86 set but unclassified = MISSING |
| Pad -> pin | 84 of 84 classified sites map to a package ball |
| IO fields on the 84 | bus-hold, direction, pull-up: default (84); slew / drive / open-drain default (53, outputs and bidir); termination default (44); standard 0 decoded = 84 MISSING |
| Option bits | 14 of 320 differ from a Quartus-built reference (lanes 0, 1, 3); meaning not decoded: all MISSING |

- M9K mode / width / init, MAC mode / coefficients, PLL, transceiver: not decoded (MISSING). Block-input mux for M9K sits at a coordinate not mapped to the M9K column, so input edges are not attributed.
- IO field decode matches value rows from the pair builds exactly; a site that equals no row is MISSING. Only sites whose four key groups equal a default pattern are classified, so non-default IO settings are not reached.

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
