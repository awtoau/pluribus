# AF3 single-wire engine of the third-party EP4CGX150 image (2026-10-31, #165)

Structure only. Tags: V = traced or simulated here, I = inferred, U = unknown. Image path only via env `PLURIBUS_DJI_IMAGE`.
Scripts: `cycloneiv_clean_af3_engine.py` (cone extraction + Verilator build), `af3_engine_tb.cpp` (testbench + virtual 1-Wire slave, DUMMY secret), `af3_engine_check.py` (engine vs reference SHA-1), `af3_engine_report.py` (groups, bus timing, program trace, pass/fail), `cycloneiv_clean_ram_consumers.py`, `cycloneiv_clean_m9k_we_ctl.py`, `cycloneiv_clean_tdp_we_check.py`. Test `tests/cycloneiv_clean/test_af3_engine.py`.

## Model
- Cone = 218 FFs of the B14-clock domain + 893 LUT / carry cells + port A of M9K 7_85 / 7_86 + pad AF3. Cell semantics = `emit.py` verilog(); port B (serial loader) idle, initial content only.
- Two LEs feed their own pin (undecoded register, ring in the netlist): self pin tied 0.
- RAM write enable of the engine = the lifted `we_b` control (writes on ops 2 and A). `emit.py` now applies `RAM_WRITE_ENABLE_INVERT` directly (#178), baked into `we_b` as a `(!net)` expression; the AF3 extractor's `WEMODE` parameter is a pure enable gate against that control, not a polarity selector -- the old pre-#178 manual double-inversion (`WEMODE=2`) was removed as wrong against the current lifter (#181 pt 1). Evidence: the raw invert pair (1,0) is unique to these 2 of 542 tiles; applying it makes the engine run bit-exact SHA-1, while ignoring it zeroes constants and program (V).
- Power-up: all FFs 0, RAM output latch preloaded with the entry word (V: the first fetch at 0x120).

## Memory map (V)
- 0x100..0x104 working state a..e; 0x105..0x108 K0..K3 (public constants); 0x109..0x10f scratch / received bytes (0x10b..0x10f = the five MAC words read from the bus); 0x110..0x11f message block W0..W15; 0x120..0x1a6 program.
- Block layout: W0 and W12 hold the two fixed key words written by the unmodified engine: W0 = `0x01118789`, W12 = `0x79465213`, hence message-order key bytes `01 11 87 89 79 46 52 13` (V). W1..W8 zero; W9, W13 (pad 0x80), W15 (length 0x1B8 = 440 bits) preloaded; W10 / W11 written from the bytes read by Read ROM. The key words remained identical when the virtual ROM ID and slave MAC secret were varied (V).

## Instruction format (word bits 15..0; I except where marked)
- [15:12] op, [8:4] data address (0x100 + field) for LD / ST, [3:0] register / lane / count, [11:4] immediate byte for TXB.
- Decode FFs (V, netlist): one-hot for ops 9 F 7 3 2 B A 1 4 8; ops 5 6 C D E 0 decoded by LUTs. Micro-step = 3 clocks (phase ring ff_9_84_8/9/12); IR loaded on the strobe; RAM address alternates PC / data address.

| op | class | evidence |
|---|---|---|
| 0 | NOP (pads 0x16c..0x176) | V trace |
| 1 / 2 | LD / ST word to or from a register (write enable = ops 2 and A) | V trace, SHA-1 loop |
| A | store variant (write enable) | V netlist |
| 3 4 7 8 9 B | ALU, rotate, f-function select, round-range skip, select (SHA-1 round body 0x177..0x196) | I (loop gives bit-exact SHA-1, per-op split not verified) |
| 5 | CMP, five times after the loop; enables the flag chain ending in ff_6_90_6 | V sim |
| 6 | END (program halts at 0x1a6) | V sim |
| C | WAIT / bus reset: imm 0 = low 19199 cycles; imm 0x20 = 400004 cycles | V sim |
| D | TXB: send imm byte (n = 0) or n bytes of a register word | V sim |
| E | RXB: read n bytes (n = 0: one byte, CRC position) | V sim |
| F | LOOP (80 rounds) | V sim |

## Bus sequence (V, simulation with a virtual DS28E01-class slave)
1. Reset (low 19199 cycles) / presence wait.
2. 0xCC (Skip ROM), 0x0F (Write Scratchpad), TA1 0x80, TA2 0x00, 8 data bytes (RAM words), read 2 CRC bytes.
3. Reset / presence, 0x33 (Read ROM), read 8 bytes (3 + 4 + 1 CRC position), bytes stored to W10 / W11.
4. 0xA5 (Read Authenticated Page), TA 0x1F 0x00, read 4 bytes (data, 0xFF, CRC-16), WAIT 400004 cycles, read 20 MAC bytes (five words to 0x10f..0x10b).
5. Bus reset, then block fix-up writes, 80-round SHA-1 loop, five LD/LD/CMP, END.
- No presence: after the first reset pulse the engine waits indefinitely (4 M cycles, no retry). Pad AF3 has pull-up OFF in the image: the line needs an external pull-up.
- ROM CRC-8 / data CRC-16 handling not decoded (the 8-FF and 10-FF registers are CRC-shaped, I).

## Timing (V arithmetic, I clock)
- Cycles: reset low 19199, write-0 low 2399, write-1 low 39, read slot low 200 (40 us hold after a 0), slot period 2561..2802, WAIT 400004. All are integer microseconds at 40 MHz (480 / 60 / 1 / 5 / 40 us, 10 ms). Standard-speed 1-Wire needs 20..40 MHz for these cycle counts (reset 480..960 us), so the engine clock is a derived clock below the Fin interval 54.9..83.3 MHz (U: which counter).

## SHA-1 datapath (V)
- R32 (32 FFs, ena lc_6_89_10; D = LUT(op 9 select, neighbour, self, W32 bit)), W32 (32 FFs, loaded from the RAM word), 31-LE carry chain adder, 8 + 7 + 8 + 10 FF side registers.
- With the two key words replaced by dummy values: round 0..79 equals the reference SHA-1 compression of the block; the engine compares raw a..e (no final IV addition) with the five MAC words in order (0x100+i vs 0x10b+i). A slave sending words e,d,c,b,a each little-endian from raw a..e makes the flag FF ff_6_90_6 = 1 in simulation; seven other byte orders and a one-bit-flipped MAC leave it 0.
- Without replacement, the engine writes W0 = `0x01118789` and W12 = `0x79465213`. Configuring the virtual slave with the corresponding 64-bit key `0111878979465213` makes ff_6_90_6 = 1; flipping one returned MAC bit clears it (V). This identifies the value as the authentication key used by this captured FPGA image, subject to the serial-loader caveat below.

## Result (V sim, structural closure V)
- ff_6_90_6 is the only FF that differs pass versus fail apart from one data bit. After the MAC read the AF3 edges and the RAM address / write-enable sequence are identical in both runs (5,402 events).
- Forward closure from the flag, the RAM outputs and both ports: sinks are pad AF3, the 2 M9K tiles and engine-domain FFs only; no other clock domain, MAC, radio path or other pad. The serial-side chain reads port B back into the same tiles only.
- Verdict: result is dead logic as far as the netlist goes (no consumer); the engine starts from configuration with no enable from the MCU side; no gating of the radio path found.

## Open
- Whether the MCU-driven serial loader ever replaces the program/key material on physical hardware; no firmware path doing so has been found.

## ASDATA self-loop bug found and fixed (2026-10-31, #183)
- #181 pt1 regenerated this engine's test fresh from the decoder and found W0/W12 = `00000000` at current HEAD, superficially looking like a regression from `196864755` (F-020). Direct rebuild-and-compare proved otherwise: `emit.py` from `070f0c385` (pre-F-020) produces a BYTE-IDENTICAL AF3 cone (`engine.v`, all 218 FFs' d/ena/aclr/sclr, both M9K tiles, the AF3 pad) to current HEAD, and running that pre-F-020 `nl.pkl` through the current test harness ALSO gives W0/W12 = `00000000` -- the bug predates F-020 and is unrelated to it; the `070f0c385`-reproduces-the-key claim in the prior version of this note was never actually re-verified by rebuilding and was wrong.
- Root cause: 15 of the engine's 218 FFs (the a/b/c/d/e round registers' LEs) have `LE_USE_REGISTER_FEEDBACK` set because their comb LUT genuinely reads its own register (one of 4 LUT inputs, used by the SHA-1 round function `next_state = f(state, ...)`) -- correct, F-010's validated case. But `emit.py._asdata_source` (pre-#183) also used this same bit to resolve these LEs' INDEPENDENT sload/ASDATA source (W-schedule feedback from the two M9K tiles, confirmed by the plain LE_LUT_INPUT lookup resolving to real `m9k_7_85_o[*]`/`m9k_7_86_o[*]` signals), wrongly overriding it with a self-loop (`d <= d`, held at reset = 0 forever). Fixed in `_asdata_source` (F-020 pt2, `cycloneiv-clean-ffctl.md`): the plain lookup now runs first, register feedback only as a last-resort fallback.
- Verified at the fixed commit: unmodified engine writes W0 = `0x01118789`, W12 = `0x79465213` again (`tests/cycloneiv_clean/test_af3_engine.py`, fresh rebuild), matching the documented key `0111878979465213`. New targeted specimen `corpus/cycloneiv/gxct_e_regfb_sload` (`scripts/cycloneiv_clean_regfb_sload_specimen.py`) closes the coverage gap that let this ship: one LE with comb-LUT register feedback AND an independent real ASDATA source, registered in the fast/full gate corpus.
- Per-op split of ops 3 4 7 8 9 B; CRC handling; the derived clock; the serial loader source types T367 / T369.
