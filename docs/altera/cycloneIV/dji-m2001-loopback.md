# DJI m2001 — TX-first / loopback simulation (#189 steps 2-4)

Gate-level sim of the lifted image (RTL emit, Verilator) driven with the real m1400 SPI0 traffic. Tags: **V** observed in sim, **I** inferred, **U** unknown. Capture-derived figures are labelled *(capture)*.

## Setup

- Script: `scripts/cycloneiv_clean_loopback_sim.py` (`build` / `stim` / `run` / `analyse` / `rxgen` / `probes`); record builder `scripts/cycloneiv_clean_uplink_record.py`. Work dir `tmp/loopback/`, log `tmp/logs/loopback_sim.log`.
- Netlist/RTL: `tmp/image_sim_dji_push/` (rtl vs flat equivalent over 20k cycles). Build 60-70 s / 7 GB; sim ~16-21k clk_main cycles/s with probes.
- Clocks (emit has no PLL; TB-driven): clk_main 100 MHz, pll_b 50 MHz, pll_c 5.6 MHz (U), B14 40 MHz, N25 DATA_CLK 22.4 MHz.
- Stimulus, all from awto-dji (`scripts/re/m1400_fpga_script_decode.py`, `re/ghidra-projects/m1400_radio/m1400_dump.txt`):
  - boot table mode 3: 512 `[0E reg val]` (full regfile twice, reg0 bit7 = copy select), mode writes; the 2,607 bridged AD9363 writes skipped (radio not in sim)
  - post-boot `[0E 01 02]` + reg0 bit0 pulse (FUN_00015b86/FUN_00015b5e); link start: ID regs 3..7 under reg0 bit7, band words 0xBA..0xBE (FUN_0001755c/FUN_00016850/FUN_00016896)
  - per frame (FUN_000171a6 TIMER1 schedule): status reads; band switch 2.4 GHz (FUN_00016ef6: radio 0x004=03/0x005=11 via bridge, 0xB0..0xBE); 56-byte uplink record to 0x44..0x7B + ID block 0x40..0x43/0x7C..0x7F (FUN_0001698a); hop words
  - record CRCs from the firmware tables (V): CRC-16 reflected 0x8408 init 0x55AA; CRC-8 reflected 0x8C init 0xAA (after the 8-byte XOR). Header/stick/key contents are placeholders (U).
- Sim readback of reg 0 returns a rotating single bit (04,02,01,40,...), not the register → stimulus uses an MCU-side shadow instead of read-modify-write. Readback path is a separate open item.

## Results

| Item | Result | Tag |
|---|---|---|
| Regfile writes | load bit-exact in the copy selected by reg0 bit7: reg0=0x08, reg1=0x02 (engine mode), reg2 copy1=0x15, reg9=0x0A/0xDF, record 0x44=0x01, 0x45=0x10 (0x12^key), 0x7B=0x3D (CRC-8) | V |
| Frame counter `cnt_65` (21 FF, (32,89)/(32,90)) | free-running, wraps every **1,400,001 clk_main = 14.000 ms at 100 MHz**, independent of stimulus | V; matches the 14 ms frame *(capture)* |
| Frame FSM (38,86)/(39,86) | settles at state 2 after boot, never moves; AC8 stays high from 9.45 us, AB12 static | V |
| FSM inputs | reg 0x02 copy1 bits (`ff_38_88_9/12`, `ff_37_84_0/3`) + RX-side frame-detect FFs (`ff_35_67_0`, `ff_38_79_4`, `ff_33_88_*`, `ff_37_86_*`) | V (structure) |
| TX path | playback-RAM write-enable leaves toggle; its 12 data inputs and the 12 pad retime FFs stay 0 → TXD = 0 throughout | V |
| R25 | toggles 50 % duty continuously (TX clock/frame output) | V |
| TX bit order | pad → RAM lane bit (V): L26,L25,K26,J26,H26,H25,G25,H24,F26,G26,E26,E25 = bit 0..11; pins.tsv `TXD_n` draft labels run the other way | V |
| RX bus order | M25,T25,T24,U26,U25,V26,W26,W25,W24,Y25,Y24,AB26,AA25 → M9K (52,74) data[0..12] | V |
| Radio-SPI engine, unforced | emits no frames of its own over 3 frames; every radio frame seen is MCU traffic relayed in mode 1 | V |
| Received-ID register (33-34,89-90) | shifts continuously (descrambler sequence; demod input idle), no comparator match, `cnt_82` idle | V |

### Bypass (Verilator force, one RX-sync FF pulsed 2,000 cycles per 14 ms frame)

- `ff_35_67_0` forced: no downstream change.
- `ff_38_79_4` (`sr_13[2]`) forced: the next stages come alive (V):
  - `cnt_82` (24-bit timer behind the ID-match combiner) starts counting
  - the deserialiser (31,65) loads
  - the radio-SPI engine issues 6 AD9363 frames, SCK = 3 clk_main/bit (33 MHz): `R 0x2B0`, `R 0x2B5`, `W 0x0FA=0xE0` (x2), `R 0x2B0`, `R 0x2B5`
    - UG-672: 0x0FA = AGC Config 1, 0xE0 → gain-control mode 00 = manual; 0x2B0 = Rx1 gain index (readback), 0x2B5 = Rx2 slot
    - reading: on RX lock the FPGA reads both gain indices and freezes the AGC (I)
  - frame FSM, AC8, TX data still static → the TX slot needs more than this one event (U: ID match and/or reg 0x02 mode)
- No engine write to 0x00A..0x00F seen → the "/64 BBPLL divider" in section 3 of `docs/lightbridge-fpga.md` comes from the MCU boot script (AD_WR 0x00A=0x06 in the mode-3 table), not an FPGA rewrite in this sequence. **U** for other engine triggers.

### Engine control registers as the MCU loads them (boot tables, V)

| Reg | mode3/mode1 copy0 | mode3/mode1 copy1 | mode0 copy0 | mode0 copy1 |
|---|---|---|---|---|
| 0x12 | 00 | 20 | 00 | 2C |
| 0x13 | 00 | 20 | 10 | 25 |
| 0x1B | 00 | 12 | 00 | 12 |
| 0xA0 | 00 | 38 | 04 | 2E |
| 0xA1 | 00 | AC | 0F | AC |
| 0xBF | 00 | 00 | 00 | 00 |

None decodes as an AD9363 clock register address; meaning **U**.

### Real downlink RX (secondary — public captures are not relied on)

- Zenodo `DJI_matrice_100_2G.bin` (SHA-256 verified), burst at +16.52 MHz *(capture)*, mixed/LPF/resampled to 11.2 MS/s *(capture-derived rate)*, 12-bit, 2R2T DDR on the 13 RX pads with N25 as DATA_CLK; 474,836 words played.
- No sync: received-ID register unchanged in character, comparator idle, demux/FIFO/AC11/AC10 static. Not treated as a lift fault: stimulus fidelity (frame pad unknown, channel order, AGC level) is unverified.

### Loopback

Not possible yet: TX produced no samples (TXD = 0), so there is nothing to feed back. The uplink and downlink are also different modems (narrow hopping vs 1024-FFT OFDM *(capture)*), so a loopback non-sync would not be a lift fault.

## Lift faults found

- None localised to a cell. Candidates for the stall: (a) the TX slot is legitimately slaved to RX lock (I, consistent with forced-sync partial wake-up); (b) reg-0 readback rotates instead of returning the register (sim artefact or lift fault in the MISO mux, U).

## Not done

- Constant-fold of the boot configuration + yosys opt (#189 follow-up 1).
- Forcing the ID-match combiner `lc_37_90_12` directly: LUT outputs are not named in the RTL emit, so it cannot be forced by name; needs the flat emit.

## Reproduce

```
python3.15t scripts/cycloneiv_clean_loopback_sim.py build
python3.15t scripts/cycloneiv_clean_loopback_sim.py stim --frames 3 --out stim_tx.txt
python3.15t scripts/cycloneiv_clean_loopback_sim.py run --tag tx --stim tmp/loopback/stim_tx.txt --cyc 14000000
python3.15t scripts/cycloneiv_clean_loopback_sim.py run --tag f1 --force 1 --stim tmp/loopback/stim_tx.txt --cyc 6000000
python3.15t scripts/cycloneiv_clean_loopback_sim.py analyse --tag tx; ... probes --tag f1
```
Probe set: `tmp/loopback/probes_extra.json` (regfile bits from `tmp/dji_spi/image.json` via `cycloneiv_clean_image_sim.spi_regs`).
