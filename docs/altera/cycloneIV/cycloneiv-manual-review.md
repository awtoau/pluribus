# Cyclone IV GX (EP4CGX150, F896 = DF31) manual review of the decode (#165, 2026-10-30)

Goal: separate real-world device restrictions from decode faults. Source = official Altera/Intel documents only; short quotes, cited by volume / chapter / page.
Static reading only: no code or data changed. Third-party PDFs stay in the vendor store (`~/vendors/altera/cyclone-iv/`, manifest in `~/vendors/altera/README.md`), not in the repo.

## Sources (all page counts verified with `pdfinfo`)

| Short | Document | Rev | Pages |
|---|---|---|---|
| HB1 / HB2 / HB3 | Cyclone IV Device Handbook Vol 1 (ch 1-11), Vol 2 (transceivers), Vol 3 (datasheet), one PDF `cyclone4-handbook.pdf` | CYIV-5V1-2.2, 2016 | 490 (= 268 + 168 + 54) |
| DS | Handbook Vol 3 Device Datasheet (standalone) | | 54 |
| ES | Errata Sheet for Cyclone IV Devices ES-01027-2.5 | 2017-04 | 12 |
| PCG | Cyclone IV Device Family Pin Connection Guidelines PCG-01008-1.6 | 2013 | 14 |
| PIN | EP4CGX150 Pin Information (PDF + TXT + XLS), F896 / F672 / F484 columns | v1.1 | 14 |
| AN592 | AN 592 Cyclone IV Design Guidelines | 2013-08 | 57 |
| PKG | Package Information Datasheet (mature devices) | | 182 |

- Not obtained: AN 447 (3.3 / 3.0 / 2.5 V interfacing, cited by Quartus warning 169177) and AN 595; neither is on docs.altera.com (search 2026-10-30). Warning 169177 itself is advisory (KB 340086 names AN 447; HB1 ch 8 p. 8-5: "All I/O inputs must maintain a maximum AC voltage of 4.1 V"). It restricts the board, not the bitstream.
- No Altera document publishes .sof / .pof / .rbf / .jam / .jbc internals, frame structure, USERCODE position or option-register layout. Only per-die published bit count: HB1 Table 8-2.

Status key: CONSISTENT (manual agrees with our decode), CONTRADICTS (manual disagrees with a statement in the tree), GAP (manual defines behaviour we have not decoded / modelled), NOT COVERED (manual silent or not compared yet).
Pin balls below are F896; pin file = PIN TXT.

## (a) Pins

| ID | Restriction | Ref | Status | Implication |
|---|---|---|---|---|
| A1 | Dedicated clock pins CLK[4..23] = DIFFCLK_0..9 p/n; input only; feed GCLK, PLL, fabric | HB1 ch 6 Table 6-3 p. 6-12 (CLK column "Input"); PCG p. 2; PIN | CONSISTENT | blocks 60 / 61 = 10 p + 10 n pads; fitter refuses outputs at 4 of 24 sampled sites; input-only is a device property, not a fault |
| A2 | 475 user I/O on F896 in 11 banks | HB1 Table 1-4 p. 1-6, Table 1-2 p. 1-4 | CONSISTENT | PIN TXT: 455 `IO` + 12 `CLKIO` + 8 `REFCLK` rows with an F896 ball = 475; banks 3, 3A, 3B, 4, 5, 6, 7, 8, 8A, 8B, 9 = 11 |
| A3 | Clock pin used as user input has no I/O register; must use an LE register | HB1 ch 5 p. 5-10 | NOT COVERED | prediction: no INREG groups at blocks 60 / 61 sites; do not emit an input register for clock-pad inputs |
| A4 | Bus hold not on dedicated clock pins; pull-up not on config, JTAG, clock pins | HB1 ch 6 p. 6-4, 6-5 | CONSISTENT | clock pads carry only IOST + PCI clamp groups (`docs/altera/cycloneIV/cycloneiv-clean-io.md`) |
| A5 | Bus hold and weak pull-up are mutually exclusive; bus hold off for differential | HB1 p. 6-4 | CONSISTENT | pair builds set one at a time (bit 10 vs 11); a pin with both is illegal, so no state is missing |
| A6 | VREF: one bus per bank, VREF pins of a bank shorted; unused VREF pins are normal I/O (higher capacitance); bank 9 has no VREF and shares bank 8's | HB1 p. 6-20, Table 6-5 p. 6-21 | CONSISTENT | PIN: 18 VREF pads (3 per bank 3..8, e.g. AE11 VREFB3N2); bank 9 balls list group VREFB8N2 |
| A7 | VREF has an electrical role only for voltage-referenced standards (SSTL / HSTL) | HB1 p. 6-20, 6-22 | CONSISTENT (the 13 MISSING sites were CFF check cells, E-R8) | "MISSING" IO sites are VREF-pad overlap in the tree (`cycloneiv-clean-io.md`, #168). All 13 MISSING sites sit in designs on the default standard (0 from non-default standards, E-R5), and none of the 12 ball-named sites is a VREF pad (AD16 AG7 AE19 A23 AG19 G14 AG18 N21 Y19 AG20 C29 H25 are `DIFFIO_*` pads). The manual gives no VREF mechanism for them. Lead only: 6 of 12 in bank 4, consecutive DIFFIO numbers B46n/B47p/B48n and R6n/R7p; see issue |
| A8 | Differential pairs: true LVDS / RSDS / mini-LVDS / PPDS outputs only on right banks 5, 6; other banks emulate with two single-ended outputs + external resistor network; true LVDS receivers on top, bottom, right except bank 9; p/n not always adjacent balls | HB1 p. 6-24, Table 6-2 note 3, Table 6-3 note 10 | CONSISTENT | LVDS input uses both pads (p IOST 11, n unused 3 -> 11); `*_E_3R` outputs build, plain LVDS / mini-LVDS outputs refused at the sampled pads. Sampled pads' banks not recorded: confirm none was in banks 5 / 6 |
| A9 | GPIO LVDS receiver: external 100 ohm termination; no on-chip differential termination on GPIO (Rd OCT exists on transceiver RX only) | HB1 p. 6-22; HB2 | CONSISTENT | expect no differential-termination CFF group at GPIO sites |
| A10 | Tri-state control not available for true differential outputs | HB1 Fig 6-1 note 1 | GAP | differential output sites must show no OE register / OE mux; unchecked |
| A11 | Differential SSTL / HSTL only on clock inputs and PLL output pins; LVPECL clock inputs only; PPDS / RSDS / mini-LVDS outputs only | HB1 Table 6-3 notes 5-7 | NOT COVERED | an `in` build of these on a non-clock pad must be refused: not tried |
| A12 | Config pins on F896: nCEO AE7 (bank 3, DIFFIO_B1n), CRC_ERROR AD6, INIT_DONE AE8, DATA0 A3, DATA1/ASDO G9, nCSO B4 (bank 9), CLKUSR A4 (bank 8), DCLK B3 (bank 9, dedicated), DATA2-4 bank 8, DATA5-7 bank 3, DEV_OE AF28 / DEV_CLRn AF27 | PIN; ES Table 3 Part 3 (F31 column); PCG p. 2-3; HB1 Table 8-18 | CONSISTENT | `~ALTERA_DCLK~` on B3 and the bank-3 `NCEO` fixed pad match. Two independent documents give the same balls. HB1 Table 8-18 puts DEV_OE / DEV_CLRn in bank 6; PIN says B5. PIN wins (handbook-internal mismatch) |
| A13 | DCLK is a dedicated config pin (output in AS, input in PS / FPP); user I/O only after configuration; Quartus lists it as an output in every build | PCG p. 3; HB1 Table 8-18 | CONSISTENT | the 4,006 "missing" `~ALTERA_DCLK~` entries are not design ports: expected, not faults (already excluded, E-R5) |
| A14 | In AS mode DCLK, nCSO, DATA0, DATA1/ASDO stay active in user mode unless "Enable input tri-state on active configuration pins in user mode" is set; their dual-purpose settings are then ignored | HB1 Table 8-18 note 2 | PARTIAL | pads A3, G9, B4, B3 are not ordinary HIO sites; "5 device-fixed pads" (io doc) lists nCEO + VIO only. Expect these 4 to be fixed or option-dependent |
| A15 | JTAG TCK / TMS / TDI / TDO, nCONFIG, nCE, MSEL[3:0], CONF_DONE, nSTATUS: dedicated, no IOE features (no OCT, no clamp) | HB1 p. 6-6, 6-11, Table 8-18; PIN | NOT COVERED | no IO site expected (`no_site` list contains only clock pads + B3): consistent by absence, never asserted |
| A16 | JTAG IOE reconfiguration: CONFIG_IO loads the "I/O configuration shift register (IOCSR) chain" | HB1 ch 8 p. 8-57 | CONSISTENT | IOCSR = our CFF (31,060 bits, periphery frames), separate from CRAM (E-H1); supports "IOE settings are CFF" |
| A17 | Bank VCCIO: one VCCIO per bank; banks 3 and 9 support only 1.5 / 1.8 / 2.5 / 3.0 / 3.3 V (no 1.2 V) | HB1 Table 6-3 note 4 p. 6-13; PCG p. 4 | CONSISTENT | pair build "1.2 V out": 16 of 20 output-capable sites = 20 - 4 bank-3 sites. Exact match: the refusals are a device rule |
| A18 | Voltage-referenced standards in one bank must share VREF and VCCIO (SSTL-2 and SSTL-18 cannot coexist); any mix of single-ended / differential standards with equal VCCIO is allowed | HB1 p. 6-20, 6-22 | CONSISTENT | corpus designs are fitter-accepted, so none breaks this. Pair builds change one pin at a time |
| A19 | LVTTL / LVCMOS 3.3 / 3.0 / 2.5 V inputs share one input buffer; thresholds follow bank VCCIO | HB1 p. 6-22 | CONSISTENT | "2.5 V = 3.0 / 3.3 V LVTTL / LVCMOS / PCI as inputs: IOST 0000, same bits" is a device property: the equivalence class is real, not a decoder blind spot |
| A20 | Drive strength per standard: 3.3 V LVTTL 4, 8; 3.3 V LVCMOS 2; 3.0 / 2.5 V LVTTL 4, 8, 12, 16; 1.8 / 1.5 V 2..16 mA; 1.2 V up to 12; SSTL / HSTL fixed classes | HB1 Table 6-2 p. 6-7 | GAP | only 2.5 V drive was built (4 / 8 / 12 / 16 / min / max, matches the 2.5 V set). Other standards: not built |
| A21 | Default output setting is 50 ohm series OCT without calibration (25 ohm for Class II), not a mA value | HB1 Table 6-2 note 1 | CONSISTENT | explains: unassigned drive "Default" differs from explicit 8 and 12 mA; 50 ohm series = 0 CFF bits (I-007); SSTL-2 Class I out = 0 bits (50 ohm default equals the 2.5 V base). Counted as expected |
| A22 | Programmable current strength and RS OCT are alternatives on the same driver | HB1 p. 6-4, 6-6 | CONSISTENT | 25 ohm series changes 7 bits like a strength setting; model as one driver-strength choice. Whether it reuses the strength groups is untested |
| A23 | Slew-rate option only with strength >= 8 mA; not with OCT with calibration, nor 3.0 V PCI / PCI-X, 3.3 V LVTTL / LVCMOS (fast only); default slew 2 | HB1 p. 6-4, Table 6-2 note 6 | CONSISTENT | slew 2 = base pattern (0 bits), 0 and 1 differ. Prediction: 3.3 V LVTTL pins carry no slew bits: untested |
| A24 | PCI clamp diode available for 3.3 / 3.0 / 2.5 V LVTTL, LVCMOS, PCI, PCI-X only; on by default for such inputs; dedicated config pins have none | HB1 p. 6-6, Table 6-3 note 2 | CONSISTENT | `io_decode.json`: clamp = 0 at 20 / 20 sites for 1.8 V input, SSTL-2 Class I input and bidir; 1 at the 2.5 V input base. LVDS input clamp 0. Exact match with the availability list |
| A25 | Unused pins have five states: tri-stated input, output driving ground, output driving unspecified signal, tri-state with bus hold, tri-state with weak pull-up (default: weak pull-up) | AN592 p. 20; PCG note 12 | CONSISTENT (2026-10-30: bus-hold state decoded, 3 builds; see clean-io unused-pin table) | io doc has 3 distinct patterns (tri-state, weak pull-up, ground = unspecified). Bus-hold unused state not built (expect IOST 3 + bit 10) |
| A26 | Registers inside one IOE share one preset / clear source; power-up high or low selectable | HB1 p. 6-6 | NOT COVERED | explains why registered-IO builds hit USE_CLR_INREG / OUTREG / OEREG groups together; no check |
| A27 | PLL clock inputs are dedicated pins only; "general I/O pins cannot drive the PLL clock input pins" | HB1 ch 5 p. 5-18 | NOT COVERED | netlist check available: every PLL inclk source is a clock pad or clock-control block fed by a pin / PLL |
| A28 | RUP / RDN OCT pins: banks 4, 5, 7 on GX (RUP2/RDN2 AD24/AE24, RUP3/RDN3 AD25/AD26, RUP4/RDN4 G25/F25); pins are normal I/O if unused | HB1 p. 6-9; PCG p. 3; PIN | NOT COVERED | MISSING sites do not include these pads; calibration block per bank 4 / 5 / 7 is untested (RS OCT with calibration builds absent) |
| A29 | RS OCT with calibration "not calibrated to the intended value" | ES p. 10 | CONSISTENT | applies to EP4CGX15 / 22 / 30 only: not our die |

## (b) M9K

| ID | Restriction | Ref | Status | Implication |
|---|---|---|---|---|
| B1 | 720 M9K blocks (6,480 Kbit), 9,216 bits per block with parity | HB1 Table 1-2 p. 1-4; ch 3 p. 3-1 | CONSISTENT | docs: 720 instances, 6,635,520 = 720 x 9,216 content bits; INDEX_PERIOD 36 x 256 = 9,216 |
| B2 | Widths x1, x2, x4, x8, x9, x16, x18, x32, x36 (depth 8192 .. 256) | HB1 Table 3-1 p. 3-2 | CONSISTENT | `WIDTHS` 9 layouts, all located (M-006) |
| B3 | Parity bit per byte is an ordinary data bit; no parity function | HB1 p. 3-3 | CONSISTENT | x9 / x18 / x36 widths use the 9th bit as data |
| B4 | Byte enables only for write widths x16, x18, x32, x36; masked bytes keep old data; with New Data, masked bytes show OLD data on the output | HB1 p. 3-3 / 3-4 | GAP | 62 memory-sim fails are exactly the 16-bit `gxm9k_w_*` / `gxm9k_m_*` families with byte enables. The manual defines the missing output rule (per-byte old / new). Candidate cause; behavioural model must mix old and new bytes |
| B5 | Same-port read-during-write: New Data or Old Data; mixed-port: Old Data or Don't Care; read or write clocks at one address: output unknown | HB1 p. 3-15..3-17 | GAP | output at a simultaneous same-address read / write in Don't Care or two-clock modes is undefined: such sim mismatches are expected, not faults. RDW mode bits (M-007) still specimen-only |
| B6 | Modes: single-port, simple dual-port, true dual-port, shift register, ROM, FIFO; FIFO and shift register need LE control logic | HB1 Table 3-1, p. 3-7 | CONSISTENT | docs: "FIFO: soft logic, no M9K mode"; shift register has no mode group either |
| B7 | True dual-port: widest x16 / x18, no x32 / x36 | HB1 Table 3-1 note 2, p. 3-11 | CONSISTENT | 36-bit blocks are single-port or simple dual-port; flagged-not-modelled count (28 dual-port, 125 wide) is in that space |
| B8 | Mixed width: simple dual-port and TDP allow ratios inside the 8-bit family (x1..x8, x16, x32) or inside the 9-bit family (x9, x18, x36); cross-family combinations are illegal | HB1 Table 3-3, 3-4 p. 3-9..3-11 | NOT COVERED | decoded `m9k.index` has one width per block; a block with port A / port B widths is never produced. Expect 2 widths per block only inside a family |
| B9 | Packed mode: two single-port RAMs per block, each <= half and <= 18 bits wide, single clock | HB1 p. 3-4 | GAP | packed mode is in M-007 (specimen-only). A block that decodes as two half-size RAMs is legal |
| B10 | All inputs registered (no asynchronous inputs); async clear only on read-address registers, output registers, output latches; power-up outputs cleared | HB1 p. 3-2, 3-7 | CONSISTENT | model "input address / data / enable registered, output unregistered or one register" matches |
| B11 | Clocking modes: independent, input / output, read / write, single-clock; two clock enables per port; address clock enable (addressstall) | HB1 Table 3-5 p. 3-14 | GAP | clock / clear / CE selects are M-007; addressstall not named in our groups |
| B12 | Memory init: .mif for RAM and ROM; ROM mode address registered, output optional register, no wren | HB1 p. 3-13 | CONSISTENT | 8 of 720 blocks with content: ROM-like blocks are legal single-port blocks with write disabled; content map 0 unmapped |
| B13 | No ECC on Cyclone IV memory (parity bits only); CRC error detection does not check memory blocks | HB1 ch 9 p. 9-2 | CONSISTENT | "ECC: none" |

## (c) Embedded multipliers

| ID | Restriction | Ref | Status | Implication |
|---|---|---|---|---|
| C1 | 360 18x18 (or 720 9x9) multipliers on EP4CGX150 | HB1 Table 4-1 p. 4-2 | CONSISTENT | image: "87 of 360" |
| C2 | One 18x18 for input widths 10..18, or two independent 9x9 for widths <= 9; no 36-bit, accumulate, chain or saturate mode in hardware; adder / accumulator in LEs | HB1 p. 4-4..4-6 | CONSISTENT | 36x36 builds use 4 MAC instances + LE adders; saturation / rounding / shift / accumulation groups (`MAC_*SATAC`, `SHFTR`) are not usable on this die: "not modelled" there is expected, count them as not-faults |
| C3 | Input registers A and B independent; output register in 18 / 36-bit sections; signa / signb also have a dedicated input register | HB1 p. 4-3 | GAP | "sign registers" listed as not modelled in `cycloneiv-clean-mac.md`: they exist in hardware |
| C4 | All input and output registers of one block share one clock, clock enable, aclr | HB1 p. 4-3 | CONSISTENT | single `MAC_CLK_FAST_MUX` / CE / CLR group per tile; a "multiplier register" and "output register" give the same bits (only two register ranks exist) |
| C5 | signa high = signed; unused signa / signb = unsigned; result signed if either operand signed; two 9x9 in one block share signa / signb | HB1 p. 4-3 / 4-4 | CONSISTENT | `MAC_SIGN_INVERT` bit set = unsigned (default); `two_mult_w9` 18 wrong pins is the 9-bit row layout, not the sign |
| C6 | Output 36 bits (18x18) or 2 x 18 bits (9x9) | HB1 Fig 4-3, 4-4 | CONSISTENT | 36-bit product = `DSP_BUFFER` indices 0..35 |

## (d) PLL and clocking

| ID | Restriction | Ref | Status | Implication |
|---|---|---|---|---|
| D1 | EP4CGX150 has 4 general-purpose + 4 multipurpose PLLs (PLL_1..4 GPLL, PLL_5..8 MPLL); PLL_7 / PLL_8 are absent only in F484 | HB1 Table 1-2 p. 1-4, Table 5-2 note 3, Table 5-5 note 1 | CONTRADICTS | `cycloneiv-clean-hardblocks.md` row and P-002: "PLL_6 / PLL_7 not placeable in this package". F896 has all 8; PIN lists `PLL6_CLKOUTp/n` (AE9/AF9) and `PLL7_CLKOUTp/n` (G7/F7) balls. The restriction is by mode, see D2 |
| D2 | PLL_6 and PLL_7 support only No Compensation and Deterministic Latency modes (no Normal, Source-Synchronous, ZDB); only C0 and C4 reach GCLKs (PLL_6: C0 -> 0 3 5, C4 -> 1 4; PLL_7: C0 -> 6 9 11, C4 -> 7 10); upstream cascading only | HB1 Table 5-5 p. 5-18, Table 5-2 (Part 3), p. 5-33 | GAP | explains the failed placements if the corpus asked for Normal mode: expected refusals. Test: PLL_6 / PLL_7 with `NO_COMPENSATION` and C0 / C4 only; each missing build is then a pending specimen, not a restriction of the package |
| D3 | PLL_3 and PLL_4: no deterministic-latency mode | HB1 Table 5-5 | NOT COVERED | P-006 `USAGE_MODE 4 for NO_COMPENSATION` is one specimen; modes per PLL type are now enumerable |
| D4 | Counters: M, N, C0..C4; C counter 1..512 at 50 % duty, 1..256 otherwise; VCO phase shift = VCO period / 8 | HB1 Table 5-5 notes 5, 9 | NOT COVERED | P-004 unused counter 15 / 15 / 3 not derivable from the manual |
| D5 | PLL scan chain 144 bits: M, N, C0..C4 = 18 bits each (8 high-count + 8 low-count, rbypass, rselodd), charge pump 9, loop filter 9; CP setting 0/1/3/7, LF resistor 5 bits, LF capacitor 2 bits; bypass bit set -> other bits ignored | HB1 Table 5-7..5-11 p. 5-37..5-39 | GAP | gives the field structure to compare against `pll.py` fields (P-004 / P-006); counters hold high / low counts, so "15 / 15" = unused counter must be re-expressed as (high, low, bypass, odd) |
| D6 | Input switchover, loss of lock, user-mode reconfiguration, spread-spectrum tracking are PLL features | HB1 Table 5-5 | NOT COVERED | no group named for them in the tree |
| D7 | 30 GCLK networks, driven by clock control blocks; sources = dedicated clock pins, DPCLK / CDPCLK, PLL outputs, internal logic; blocks fed by DPCLK or internal logic cannot drive PLL inputs; left-side blocks accept no clock pin | HB1 p. 5-1, 5-10 | CONSISTENT | `CLKBUF_TILES`: 5 tiles x 6 sites = 30 buffers (B-011) |
| D8 | Static clock select is in the configuration file; dynamic select by clkselect[1..0]; clkswitch from configuration or logic | HB1 Fig 5-1 notes | GAP | static select groups are the CLKBUF input mux (S-12); dynamic select pins not enumerated |

## (e) LAB / LE

| ID | Restriction | Ref | Status | Implication |
|---|---|---|---|---|
| E1 | LAB = 16 LEs; 149,760 LEs = 9,360 LABs | HB1 ch 2 p. 2-5; Table 1-2 | CONSISTENT | 104 x 90 = 9,360 LABs |
| E2 | LAB control signals: 2 clocks, 2 clock enables, 2 async clears, 1 sync clear, 1 sync load (8; at most 4 non-global) | HB1 p. 2-6 | CONSISTENT | `LAB_INVERT` gi 0..5 = clk0 ce0 clk1 ce1 sload sclr (CUDA table); aclr inversion is not a LAB_INVERT group. The 9th CUDA line (second sload, mask 0x40) has no handbook counterpart |
| E3 | Clock and clock enable are linked per LAB (clk1 uses ena1); both edges use both LAB clocks | HB1 p. 2-7 | NOT COVERED | pairing exists in the emitted netlist via gi pairs; not asserted |
| E4 | Register packing and synchronous load cannot be used together; register packing = LUT and FF in one LE used independently | HB1 p. 2-2, 2-6 | CONSISTENT | FF-only LE: sload tied high + packed register input (E-S3): the LAB sload is spent on the packed-D path, so a packed LE cannot also carry a real sload |
| E5 | No asynchronous load: preset by NOT-gate push-back; an LE supports either preset or clear | HB1 p. 2-7 | NOT COVERED | decoder will see inverted data / output around an aclr FF for a preset register; check the emitter handles it |
| E6 | Modes: normal (4-input LUT, cin or data3) and arithmetic (two 3-input LUTs, 2-bit adder); register feedback; D, T, JK, SR types are synthesized onto the single D register | HB1 p. 2-2..2-4 | NOT COVERED | arithmetic-mode sum / carry combination not re-derived (ledger); handbook only gives the block diagram |
| E7 | Carry chains longer than 16 LEs link LABs in the same column, running vertically; chain continues "as far as a full column" | HB1 p. 2-4 | CONSISTENT | LE 15 of (x, y+1) -> LE 0 of (x, y): same column; direction / skip-half-LABs not in the manual (F-015, F-016 stay specimen) |
| E8 | Local interconnect: 16 LE outputs + row / column + neighbouring LABs / M9K / PLLs; LAB row clocks [5..0] and local interconnect generate LAB-wide control signals | HB1 p. 2-5..2-7 | CONSISTENT | six BLK_CLK_BUF lines + 4 LAB_CONTROL_MUX inputs (E-S1) |
| E9 | Chip-wide reset DEV_CLRn overrides every other clear | HB1 p. 2-7 | CONSISTENT | option "ENABLE_DEVICE_WIDE_RESET" changes the option register (27 changing ids) |

## (f) Configuration

| ID | Restriction | Ref | Status | Implication |
|---|---|---|---|---|
| F1 | EP4CGX150 uncompressed .rbf = 39,425,016 bits | HB1 Table 8-2 p. 8-5 | CONSISTENT | 4,928,127 B x 8 = 39,425,016, identical in 29 / 29 files |
| F2 | Compression shrinks the bitstream 35-55 %; per-device in the chain | HB1 p. 8-2 | NOT COVERED | compressed rbf format unpublished; the DJI image is uncompressed only if its source file is |
| F3 | Every data frame carries a 16-bit CRC; whole-stream 32-bit CRC (IEEE 802) is stored in the error-detection register at end of configuration | HB1 ch 9 p. 9-2, Table 9-3 | CONSISTENT | per-frame CRC-16 (init 0xFE54) verified 70 / 70. No 32-bit stream CRC is stored in the rbf (2026-10-30, `scripts/cycloneiv_clean_crc_loc.py`, 3 builds: BASE, CRC_ERROR_CHECKING ON, ON + divisor 256): BASE vs ON differs in 91 of 4,928,127 bytes = 21 header bytes (option lanes of bits 8, 92 + frame-0 CRC-16 at bytes 73..74) + 70 bytes of the CRC_ERROR pad cells; the last 64 bytes (postamble 0xFF) are identical, no 4-byte field changes with the CRAM content. The device computes the 32-bit CRC itself (handbook) |
| F4 | CRC divisor 2^n, n = 0..8 (9 values) | HB1 Table 9-5 | CONSISTENT | one-hot option bits 27..34, divisor 1 = 0 |
| F5 | Full CRC scan EP4CGX150: 62 ms min (80 MHz), 31.27 s max | HB1 Table 9-6 | CONSISTENT | 62 ms x 80 MHz = 4.96 M cycles = about 4.9 MB, the size of 6,154 x 796 B |
| F6 | IDCODE EP4CGX150 = version 0, part 0010 1000 0000 0100, mfg 000 0110 1110, LSB 1 = 0x028040DD; boundary-scan register 1,495 bits | HB1 Table 10-2 p. 10-4, Table 10-1 | CONSISTENT | the EP4CGX150 pcf device payload (local, `vendor-analysis/altera/analysis/ep4cgx150_pcf_payload.bin`) carries the pair (IDCODE 0x028040DD, mask 0xFFFFFFFF) exactly once, little-endian at offset 1035; test `test_config_facts.py::test_pcf_payload_carries_idcode_with_full_mask`. The assembler's check code is not read |
| F7 | JTAG instructions in the manual: IDCODE, SAMPLE/PRELOAD, EXTEST, BYPASS, CONFIG_IO, ACTIVE_DISENGAGE/ENGAGE, PULSE_NCONFIG, CHANGE_EDREG; USERCODE is not described | HB1 ch 8, 9, 10 | NOT COVERED | the USERCODE writer (`ASM_JTAG_WRITE_USER_CODE`, sof tag 19) has no handbook support; E-A1 JTAG option classes stay vendor-code only |
| F8 | GX schemes: AS, PS, FPP (50 / 75 / 110 / 150 and F484 GX30), JTAG; no AP; MSEL[3:0] pins select scheme, POR delay, voltage (not bitstream bits) | HB1 Tables 8-3, 8-4; PCG note 1, 18 | CONSISTENT | MSEL pins carry no bitstream state; the option register has no MSEL field |
| F9 | Dual-purpose pin options (INIT_DONE, CLKUSR, nCEO, DATA / DCLK as regular I/O or tri-stated) act on the pads | HB1 p. 8-62, Table 8-18 | CONSISTENT / PARTIAL | they act on the pad IO sites, not the option register (2026-10-30, `test_config_facts.py::test_dual_purpose_pad_cells`): INIT_DONE output -> site AE8 MIO_OE_INVERT (+ option bit 3); CRC_ERROR (CRC_ERROR_CHECKING) -> site AD6 MIO_OE_INVERT + MIO_DATA_INVERT (+ option bits 8, 92); nCEO as regular IO -> site AE7 MIO_OE_INVERT (+ option bit 91); DCLK as regular IO / PASSIVE SERIAL / TRI_STATE_SPI_PINS -> pseudo-site 324 (UDCLK, no ball) MIO_OE_INVERT + MIO_DATA_INVERT. DATA0 / ASDO / nCSO / CLKUSR reserve options changed nothing in the sof in the pair builds (DATA0, FLASH_NCE) or were not built (CLKUSR as IO); see docs/altera/cycloneIV/cycloneiv-clean-io.md |
| F10 | Remote system upgrade is an AS feature (errata: invalid application image fails to revert on GX) | HB1 ch 8; ES p. 4 | NOT COVERED | RSU option ids in the option table are untested; not needed for a plain lift |
| F11 | Option-register facts visible in the manual: INIT_DONE, DEV_CLRn, DEV_OE, CRC enable, divisor, user-supplied start-up clock, release clears before tri-states, nCEO, tri-state config pins in user mode | HB1 ch 8, 9; PCG | CONSISTENT | all appear among the 27 option ids that change the register (`cycloneiv-clean-options.md`) |

## (g) Errata, rules ledger, open items

| ID | Item | Manual evidence | Status | Implication |
|---|---|---|---|---|
| G1 | I-007 "50 ohm series termination = none (CFF-indistinguishable)" | A21 | CONSISTENT | not a decode gap: 50 ohm without calibration is the default driver |
| G2 | I-004 / I-005 joint IOST / strength / clamp states | A24, A23, A22 | CONSISTENT | clamp availability and slew rules explain which joint states can exist at all |
| G3 | I-009 unused-pin states | A25 | CONSISTENT | 5 states = 4 distinct patterns (ground == unspecified in CFF and CRAM), bus-hold decoded 2026-10-30 |
| G4 | I-012 VREF pad (UNKNOWN) | A6, A7 | CONSISTENT | the 3-per-bank VREF structure is in the manual; the pad -> pin map is not |
| G5 | E-Q1 IOST 3 bits (not 4) at 51 sites | none | NOT COVERED | manual silent on CFF width |
| G6 | E-R5 / E-R1 per-package ball tables | PIN F896 / F672 / F484 columns; Table 1-4 (475 / 393 / 270 I/O) | CONSISTENT | the three-column pin file is the independent oracle for `pkgpad.pins(count)` (#172); cross-check not run |
| G7 | #151 "468 of 896 balls have no die site" | PIN | CONSISTENT | 896 - 475 user I/O = 421 balls are power, ground, transceiver, config; the rest are NC / package-specific. Compare counts per function class from PIN TXT |
| G8 | P-002 PLL_6 / PLL_7 | D1, D2 | CONTRADICTS | see D1 |
| G9 | M-007 byte enable, RDW, packed, clock modes | B4, B5, B9, B11 | GAP | manual defines each; M9K sim fails of the byte-enable families have a documented candidate cause |
| G10 | M-010 / E-P4 MAC sign / input registers | C3, C4, C5 | CONSISTENT | sign registers GAP in C3 |
| G11 | C-003 global-network clock inversion (UNKNOWN) | D7 | NOT COVERED | manual silent |
| G12 | F-012 LAB lines | E2 | CONSISTENT | 8 documented signals vs 9 CUDA lines |
| G13 | B-011 clock buffer site order | D7 | NOT COVERED | count 30 agrees; order not in manual |
| G14 | T-003 / T-004 structural clock edges | D7 | NOT COVERED | manual silent |

## Errata and tech notes

Errata sheet ES-01027-2.5 (12 pp, 2017-04) is the only Cyclone IV errata document. Relevant rows for EP4CGX150 only; transceiver rows noted.

| Item | Document | Relevance | Our status |
|---|---|---|---|
| RS OCT with calibration drives the high level below tolerance | ES p. 10 | EP4CGX15 / 22 / 30 only | not EP4CGX150; no action |
| Human body model ESD | ES p. 3 | EP4CGX15 / 30 only | n/a |
| Remote system upgrade fails to revert (GX) | ES p. 4 | AS RSU option semantics | NOT COVERED, not needed |
| Ground list for refclk >= 2.97 Gbps (F31 column: AD6, AE8, AE7, AE6, AF6, AG6, G9, B4, A4, A3, F8, G8 and others) | ES Table 3 Part 3 p. 7 | confirms config-pad balls on F896 and bank assignment; Quartus enforces the rule from 11.0 | CONSISTENT with A12; pads on the list are not special in the bitstream |
| Dual-purpose pins "Do not tie to ground if used for configuration"; CLKUSR must not toggle in user mode | ES notes 5, 6 | CLKUSR A4 is bank 8 user mode input | NOT COVERED |
| PLL phasedone stuck low; rx_freqlocked stuck high; DisplayPort / SATA CDR | ES p. 2-4 | PLL dynamic phase shift and transceiver | NOT COVERED (no transceiver decode) |
| PLL cascading for transceivers not allowed | ES p. 8 | only REFCLK / DIFFCLK pins drive a transceiver PLL | NOT COVERED |
| PCIe x1 hard IP channel 0 mapping (fixed in Quartus 10.1) | ES p. 8 | hard IP not decoded | NOT COVERED |
| Quartus warning 169177 (3.3 / 3.0 / 2.5 V pins) | KB 340086, AN 447 (not obtained), HB1 p. 8-5 | board-level overshoot advice | not a bitstream property; ignore for decode |
| Pin connection guidelines: unused CLK / DIFFCLK pins to GND; default Quartus unused state = input tri-stated with weak pull-up; CRC_ERROR open drain with 10 k pull-up | PCG p. 2-3, note 12 | default unused state is a decode fact | CONSISTENT with `unused` default (weak pull-up 1 option exists; default vs "AS INPUT TRI-STATED" base: check which the corpus unused pads show) |
| AN 592: Quartus checks single-ended output placement against LVDS pads and against VREF pads / supply pairs | AN592 p. 28 | outputs near LVDS / VREF pads are fitter-restricted | explains absent combinations in the corpus; not a decode item |
| Package datasheet (F896 mechanical) | PKG | ball geometry only | n/a |
| Programming file formats (.sof, .pof, .rbf, .jam, .jbc), frame structure, bit counts per die | none published; only HB1 Table 8-2 | external confirmation of internals is impossible | F1 consistent; F3 and F6 are the only checkable facts |
| Quartus known-issues pages touching Cyclone IV GX | not found in the docs.altera.com search | | NOT COVERED |

Errata (ES) that explain or contradict `docs/reversing-errata.md`: none. Statements in the tree contradicted by the manual: D1 (`docs/altera/cycloneIV/cycloneiv-clean-hardblocks.md` PLL row, rules.tsv P-002; no E-id yet: add E-P5) and A7 (io doc VREF wording).

## Task 3

### Contradictions (2)

1. D1 / G8: "PLL_6, PLL_7 not placeable in this package" (`docs/altera/cycloneIV/cycloneiv-clean-hardblocks.md`, reference/rules.tsv P-002). F896 has all 8 PLLs; PLL_6 / PLL_7 are mode- and output-limited (D2). Fix: restate as "not placed by the builds tried (compensation mode / output counters)" and run the specimens (D2). Issue filed (P3).
2. A7: the VREF-pad explanation of the 195 (13-site) MISSING class has no support from the manual: default-standard builds, no VREF role, none of the sites is a VREF pad. Hypothesis stays open; remove the "VREF-pad overlap" wording from the pins table or label it UNVERIFIED. Issue filed (P3).

No handbook statement shows a decoded bit value to be wrong.

### Real-world impossible or refused combinations in the corpus and pair builds

- None found among fitter-accepted designs. Refused builds are device rules, not our limits: 1.2 V in banks 3 / 9 (A17, matches 4 of 20 sites exactly), outputs on input-only clock pads (A1), true LVDS / mini-LVDS outputs outside banks 5 / 6 (A8), differential SSTL / HSTL on non-clock pads (A11).
- Raw per-design pin / standard / bank sets of the 3,589 gate designs were not re-scanned for VCCIO conflicts (Quartus already enforced them). The check would need the pin assignments per design: not run.

### Expected, not faults (count in the headline as expected)

- `~ALTERA_DCLK~` on B3: 4,006 (A13).
- Dedicated clock pads: input only; no I/O register; no bus hold / pull-up (A1, A3, A4).
- Input-standard equivalence class 2.5 V = 3.0 / 3.3 V LVTTL / LVCMOS / PCI (A19); 50 ohm series = base; SSTL-2 Class I out = base (A21).
- 1.2 V refused at 4 bank-3 sites (A17).
- MAC saturation / rounding / shift / accumulate / 36-bit hardware modes: not present in hardware (C2).
- M9K read-during-write outputs in Don't Care or two-clock same-address cases (B5).
- PLL_6 / PLL_7 absent from Normal mode builds (D2).

### GAPs ranked for the DJI lift

1. B4 M9K byte-enable output rule (62 sim fails, rule written in the manual).
2. A14 / F9 dual-purpose config pads: AE8, AD6, AE7 and DCLK decoded to their OE_INVERT / DATA_INVERT cells (F9); open: A3 / G9 / B4 / A4 option-dependent cells (reserve options changed nothing in the sof for DATA0; ASDO / nCSO / CLKUSR not built).
3. D2 / D5 PLL_6 / PLL_7 specimens (NO_COMPENSATION, C0 / C4) and scan-chain field structure for P-004 / P-006.
4. F3 32-bit CRC location: closed, not stored in the rbf (above).
5. A25 bus-hold unused state: closed; A20 drive strengths of non-2.5 V standards (the DJI image uses 2.5 V default; low).
6. B8 / B9 mixed-width and packed mode (image blocks decode single width).
7. C3 sign registers.
8. F6 IDCODE check: closed (pcf payload carries it).
