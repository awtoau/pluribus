# Lightbridge ground FPGA (m2001): what we found

Third-party EP4CGX150 image = Lightbridge ground-side FPGA, module m2001. It ships inside the P3X (Phantom 3) firmware packages, but it is the only Cyclone IV image in any package: the other ground images (m2000, m2002, m2003) and every air image (m1900) are Cyclone V. m2001 is probably the Inspire 1 RC (GL658) board variant (I: wiki board marking names a Cyclone IV GX; the Inspire RC package has m2000 and m2001 but no m2002). Which hardware variant a P3 ground unit uses is not settled.
Tags: **V** traced/measured here, **I** inferred, **H** hypothesis, **U** unknown. Structure and counts only; no ROM dumps, no firmware addresses, no ID values.
Status changes fast: numbers are from the run named in each section; evidence lives in #165 / #169 / #176 comments, `reference/rules.tsv`, `docs/cycloneiv-clean-*.md`.

## 1. What it is

- Cyclone IV GX EP4CGX150, package F672 (V: 82 of 82 unbonded pads in ground state; no header field encodes the package).
- Ground side only. Air side is a separate image (m1900), die unidentified (awto-dji#3). One image cannot do both.
- Role: AD9363 digital interface + OFDM receive path + MCU control + H.264 byte output to FX3.
- Quartus-built (assumed, first-pass scope). Hard blocks used: LABs, M9K, MAC, 2 PLLs, IO, JTAG user, remote update (I).

## 2. Decode status (DJI tier run 46, fast gate run 45)

- 89,282 LUTs, 35,873 FFs (gate, emit and netlist agree), 85 used IO pads, 542 M9K with routed outputs (8 hold data), 87 MACs (2 in 9-bit mode), 2 PLLs, 6 clock domains.
- 6,154 of 6,154 frames pass CRC; 0 fan-in conflicts; 0 undriven nets; 99.05 % of set bits explained, 56.47 % validated.
- Fast gate (134 designs): pips 656,759 / 2 missing; lut_init and pins 0 missing; register_clock 3 missing.
- Readable lift: 1,377 adders, 198 subtractors, 260 comparators, 226 counters, 21 FSMs, 418 flat LUTs left of 89,282.
- Simulation: Verilator runs both flat emit and RTL (RTL equals flat on idle and SPI programs).

## 3. Radio chain

- AD9363, 2R2T (V from both MCU firmwares): both RX channels on at both ends; air enables both TX with equal power; ground ends with TX2 only (narrow uplink).
- Data port: CMOS, DDR, dual-port full duplex, frame in pulse mode, no swaps/inversions (V). With two channels: 22.4 MHz data clock, four 12-bit words per sample (I). Fref 40 MHz is inferred.
- Downlink (air TX to ground RX): 11.2 MS/s, 10 MHz RF filter, ~9.5 MHz occupied (V). Uplink (ground TX to air RX): ~1.25 MHz RF filter, narrow hopping bursts in the gaps between video bursts.
- Channel plan: 39 channels, 2404-2480 MHz, 2 MHz step, LO = 20 x N (V). P3X is 2.4 GHz only (Dan).
- Weird: ground final state has the ADC/DAC divider /64, which would give 1.4 MS/s and cannot carry the 10 MHz downlink. FPGA may rewrite it after boot (U).
- Radio init comes from the MCU firmware (about 2.6k writes air, 3.15k records ground). Nothing in the FPGA holds an init script (V: engine start is register-driven).

## 4. Air interface (public IQ, not this image)

- 1024-FFT OFDM, 10.9375 kHz spacing, Fs 11.2 MS/s, CP 1/8, symbol 1152 samples (102.86 us), 864 used carriers (k = -432..+432, DC null), 96 pilots (every 9th), ~92-97 symbols per burst, 14 ms frame (V, 19 of 19 bursts fit).
- Matches the IEEE 802.16e 10 MHz OFDMA profile in numerology (I, from memory); no 802.16e preamble, pilot placement differs, WiMAX lineage stated by public sources without parameters.
- Weird pilots: two-level amplitude alternating by pilot ordinal, complementary between the two symbols of a pair; unexplained phase steps (90 degrees in a pair, +60/-30/-30 at class boundaries); not a frequency offset (V). Two-transmitter pairing fits (I), no decoding of the data yet.
- Data carriers look Gaussian even at ~48 dB SNR after single- and two-path equalisation (V); modulation undecided. Pilot signs do not follow x^11+x^9+1 with any seed, including the image's (V, negative; mixed-path caveat).
- No FEC found in the lifted logic: no convolutional encoder, RS multiplier, CRC-32, or 802.16 header CRC-8 (V on 349 modelled M9K sinks; 193 M9K and hard IP were undecoded at that time).

## 5. FPGA to radio

- Data bus pads (I, structure only): 12 TX data, TX frame, TX clock out (clock/2 while TX on, DDR), DATA_CLK in, 12 RX data in 6 complete positive/negative pairs, RX frame guess (H), 9 enable/direction style outputs (H).
- TX path: each TX pad takes 4 M9K read bits (a 9-bit lane from a 256x36 RAM, a 3-bit lane from a second RAM); a 2-bit counter steps the 4:1 word mux; both RAMs are zero at load, so software fills them (V/I).
- RX data is captured by one FF per pad every cycle; sinks are M9K ports (now modelled): the receive pipeline is still to be traced.
- SPI master to the radio exists (V): a 24-bit frame engine, 5-bit bit counter, 19-FF word register, 2-FF phase FSM (no free-running divider: rate unknown without PLL plan), 8-FF MISO capture.
  - Mode mux on write reg 0x01 bits 1:0: 01 = bridge (MCU pads pass straight to the radio, radio MISO to the MCU), 10 = engine drives the radio pads, 00 and 11 idle.
  - The 5-byte frequency words (regs 0xB0..0xBE) feed the MOSI serialiser only. A retune = FPGA SPI engine writing PLL words to the AD9363.
  - No busy flag found; radio MISO reaches readback only at address 0xC4.

## 6. MCU interface (SPI slave)

- Pads (F672): MOSI AB11 (also seen as AG12 in older notes: same pad, different package map), SCK AA8, CS AA9 (active low), MISO AA7. Older notes using AG12/AG4 are stale.
- Frame = 3 bytes (command, address, data); 5-bit bit counter 0..23; command byte 0x0E is the write opcode (V: only 0x0E loads in a 256-opcode sweep); read opcode 0x0F is assumed (U).
- Write register file: 208 addresses (0x00..0xCF), 8 FFs each, 368 enable nets; no writes at 0xE0..0xEF.
- Weirds:
  - Register 0 bit 7 selects which of two copies of a register loads; readback returns the second copy (V).
  - Readback E2..EB: five of eight bits alias write registers (address bit 7 ignored); about 140 snapshot FFs outside the register file feed the other three bits (candidate peer-ID source, not traced).
  - The "lock" bit 0xEB bit 0 reads a write-register FF, not lock logic (U).
  - The FPGA id/version word the MCU checks was not found as a constant (U).
- ID registers: the MCU writes five ID bytes to registers 3..7 (ground). Three 8-bit equality trees compare registers 3, 4, 5 with three 8-bit groups of FFs (24 FFs) loaded from the demodulated path; registers 6 and 7 feed muxes and carry chains, not comparators (V). The combiner LUT also uses a flag FF.
- Frequency words and ID are both 5 bytes, in different register ranges (0xB0..0xBE vs 3..7); no sign they are the same thing.

## 7. Scramblers, CRC, restarts

- 3 x PRBS15 (x^15+x^14+1, seed 100101010000000: the 802.16/DVB randomiser class), 4 x PRBS11 (taps 9 and 11, seeds 10110101110 for two, 00000101111 for two, same sequence 121 steps apart), 1 serial CRC-16-CCITT (0x1021, init 0) (V; simulation holds the seeds and follows the polynomials).
- All seeds are fixed constants in LUT logic: none comes from a pad, M9K, counter or ID.
- Restart strobes are internal state; only PRBS15 #0 has an MCU-programmable restart period (96/192/384/768 clocks, two FFs loaded from the SPI shift chain). 96 and 768 equal pilots and data carriers per symbol (H); 2304 = 2 x 1152 samples (H).
- PRBS15 #0/#1 are bit-serial data XORs; the PRBS11s look like dither/gating masks (I). CRC covers the same serial stream as PRBS15 #1 (direction unknown).

## 8. M9K and the microcode-like ROMs

- 542 tiles with routed outputs: single port 359, simple dual port 178 (148 x36), ROM 3, true dual port 2; no packed/mixed width/byte enables (V).
- Only 8 tiles hold data (12,993 set bits). None holds an FFT twiddle, preamble, pilot sequence, interleaver, CRC or PRBS table (V, negative).
- Content: linear ramps (two 100-word, ~0.03 % residual), a smooth phase-like 512x18 ramp (not a sine), a 4-level staircase, decaying-exponential-like curves feeding MAC inputs (V: datapath tables, no feedback).
- No sequencer or soft CPU (V): the 680-word 9-bit + 3-bit pair is an index/parameter ROM driving the read addresses and enables of 24 downstream M9K banks. The 7_85+7_86 pair is one 32-bit true dual-port RAM written at run time: its initial content is the SHA-1 initial hash values H0..H4 and round constants K0..K3 (words 256..264, V) plus a 128-word 16-bit microprogram (opcodes undecoded). It is the working store of a microprogrammed single-wire half-duplex master on pad AF3 (V structure, I protocol); command bytes 0xCC 0x33 0x0F 0xA5 0xF0 in the program match the Maxim DS28E01 1-Wire SHA-1 command set (H, from memory). A separate 141-FF serial loader fed from the MCU SPI byte chain can write words 256..511; no firmware path that loads it was found and nothing in the modelled netlist consumes the engine's result (possibly dormant logic).
- Training/pilot/interleaver therefore come from logic, not memory.

## 9. FX3 side

- FPGA is the master of an 8-bit slave-FIFO (GPIF II): 8 bidirectional data pads with a shared OE, 7 outputs, PCLK from a toggle FF on PLL_8 (V/I), 2 flags.
- Stream: raw Annex-B H.264 (1280x720@25, High L5.0), SPS+PPS every 60 AUs, 9-AU intra-refresh sweep, 0 IDR, PKTEND after each AUD; FX3 wraps `55 CC <type><len>`. DUML never rides this port (FX3 UART).

## 10. Clocks

- 2 PLLs enabled: PLL_2 (m14, c0 50/50) and PLL_8 (m20; c0 4/4, c3 8/8; VCO post-scale 2). 6 clock domains; the main one holds ~63 % of FFs. Both PLLs take their first input from ball B14 (dedicated clock pin) through a global clock buffer, the row/LAB clock lines and the dedicated-buffer element (V); same chain for both, no PLL cascade, second inputs unused. N25 (AD9363 data clock) is sampled as data, not used as a PLL input. Fin lies in 54.9-83.3 MHz if the decoded PLL parameters hold (I); what B14 is on the board is U.
- Weird: the PLL input select lives in the periphery (CFF) address space, flagged by a fourth routing flag byte that earlier tracers ignored.

## 11. Odd facts worth remembering

- The image has 6 constant output pads (4 high, 2 low) and 10 "used" input pads with no consumer.
- JTAG user interface bits and the remote-update block are in use; no transceiver or PCIe cells differ from idle (positive control missing).
- 20 (later 0) M9K init lists once mismatched their declared depth: width came from wired pin count; fixed.
- 83 % of the image's arithmetic local-path FF claims are dead pass-through chain LEs (V): the image is full of long adders.
- The wiki-reported Artosyn chips later reproduce this FPGA design exactly (public statement, not checked).

## 12. Open

- Receive pipeline (RX pads to demodulation), TX RAM write path and I/Q order, PLL clock plan, SPI frame register mapping.
- Peer-ID readback source, lock bit, FPGA id word, ID comparator inputs.
- What the microcode-like ROMs run, and any prior art (open-source or vendor) behind the tables and control.
- Data modulation and coding on the air interface (needs a two-channel capture or the FPGA pipeline).

## Pointers

- Issues: #165 (lift, evidence comments), #169 (hard blocks), #176 (PLL input select).
- Local only (commercial): annotation table, `tmp/ad9363/`, `tmp/dji_stream/`, `tmp/dji_microcode/`.
- Tools: `scripts/cycloneiv_clean_{gate,image,annotate,spi_trace,pad_roles,m9k_*}.py`, `scripts/ad9363_regdecode.py`, `scripts/lightbridge_ofdm_demod.py`.
