# Simulation of the lifted third-party EP4CGX150 image (2026-10-30, #165)

Scripts: `scripts/cycloneiv_clean_image_build.py` (netlist pickle + flat Verilog + RTL, from HEAD), `scripts/cycloneiv_clean_image_sim.py` (prep / lint / run / forced / check / spi). Test: `tests/cycloneiv_clean/test_image_sim.py`. Outputs `tmp/image_sim/` (never committed), log `tmp/logs/image_sim.log`. Counts only; image path via env `PLURIBUS_DJI_IMAGE`.

## Setup
- The flat emit and the RTL are self-contained: M9K / MAC are inline models, no PLL model. No vendor sim library is used.
- Global clock-buffer sources (`u_clkbuf_out_*`) are module inputs. 6 are FF clocks (domains of 23,416 / 13,046 / 218 / 142 / 119 / 52 FFs), 5 are async-clear sources (11,060 / 9,338 / 4,955 / 1,977 / 746 FFs). Testbench: clears low for 4 clocks then high; all 6 clocks the same period (no per-buffer PLL mapping is decoded: `plan same`).
- 1,877 further undecoded sources + 3 hard-IP sources tied 0.
- Two one-LUT inverter rings (dependent self loops, `cycloneiv_clean_loops.py`) oscillate in zero time (verilator DIDNOTCONVERGE): the self pin is tied 0 in a derived copy (`prep`); 0 other dependent loops.
- Verilator needs lines < 40,000 tokens: `prep` splits 375 M9K init lines.
- Free of timing: zero-delay netlist, SPI/clock stimulus on a 10 ns fabric period.

## Simulator (measured under load average 15..35 on a shared box; wall times include contention)
| | flat emit (457 k lines, 99 MB) | RTL (175 k lines, 85 MB) |
|---|---|---|
| verilator lint | 146 s, 8.0 GB, 0 errors | 115 s, 7.4 GB, 0 errors |
| verilator `--binary --timing --threads 6 -O1` build | 167..266 s, 8.1..10.2 GB | 90..147 s, 7.4 GB |
| verilator run (20,000 clocks, 6 clocks) | 2.4..3.0 s with FF probes (~7 k clocks/s) | 0.6 s without probes (~33 k clocks/s) |
| iverilog -g2012 compile | killed at the 1,500 s limit (5 GB) at line 2.64 M of 3.05 M | killed at the 900 s limit (4.1 GB) |
- Choice: verilator. iverilog is not usable on the image-size netlist.

## Results
- Activity (20,000 clocks, FF toggles / FFs): domain 23,416 FFs 1.28 M toggles (64 per clock, 0.27 % of the FFs per clock); 119 FFs 40 k; 218 FFs 53 k; 52 FFs 109 k; 142 FFs 2; 13,046 FFs 13 (all in the first 16 clocks: dormant). SPI traffic adds 7.8 k toggles to the first.
- PRBS15 x3, PRBS11 x4, CRC-16 (forced stimulus: enable forced 1, strobe externals forced to the seed assignment for 40 clocks, then to the run assignment for 1,100 clocks; the control state is internal, no pad is in the cones, so natural start-up is not reachable from the pads):
  - seed held 37 / 37 clocks in every group; logical seed (FF ^ lock state) equals the recorded seed in 37 / 37 (PRBS15 100101010000000 x3, PRBS11 10110101110 x2, 00000101111 x2); CRC state 0 in 37 / 37.
  - 1,094 / 1,094 clock-to-clock transitions equal the detector structure (Fibonacci, orientation as listed), 7 of 7 LFSR groups, and CRC-16-CCITT (x^16+x^12+x^5+1, exact data bit, 1,094 / 1,094).
  - every stage stream satisfies the characteristic-polynomial recurrence (x^15+x+1: 16,200 / 16,200; x^11+x^2+1: 11,924 / 11,924); the reciprocal (the documented PRBS table form) satisfies ~50 %, so the lifted register runs the reciprocal orientation of the table polynomial.
  - 1,095 distinct states in 1,095 clocks (15- and 11-stage) - the maximal-length period is not reached in this window.
- SPI (pads: data AB11, bit clock AA8, frame AA9 active low, readback AA7; 32 fabric clocks per SCK period; command 0x0E write, 0x0F read assumed for read):
  - frame polarity: active-high shows 0 register loads in 12 transfers; active-low loads.
  - 3-byte writes to registers 0, 3..7: 8 FFs load per write, in the first copy of the register when reg0 bit7 = 1 and in the second copy when reg0 bit7 = 0 (opcode sweep 0..255 on register 3: only 0x0E loads, 256 transfers). 12 of 12 writes (reg0 x2, registers 3..7 in each copy) read back from the FFs as the written byte.
  - transfers change 97..160 FFs each (shift chain, bit counter, address register, command capture), 8..16 of them outside the main domain; 370 distinct FFs over the 22-transfer program.
  - readback (AA7): the byte read from register 3..7 equals the second copy's value in 5 of 5 reads (0x66, 0x77, 0x88, 0x99, 0xAA); reads with the second copy 0 and the first copy non-zero return 0 (5 of 5). The bit7 = 1 readback is not tested.
- RTL vs flat (same stimulus, 20,000 clocks, 53 output pads): no SPI: equal except 4 pads; with SPI: AA7 differs in 640 rows (13 high segments in flat, 0 in RTL).
  - the 4 pads (const-1 outputs in the flat emit) are left undriven by the RTL lift (`// UNDECODED: io_...`).
  - RTL AA7 never goes high under the SPI program.
