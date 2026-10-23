# Cyclone V block-mux Quartus fuzzing — status

Issue: #103 (independent Quartus verification of Mistral's `cv_block_muxes`
claims). Script: `scripts/cyclonev_blockmux_fuzz.py`. Device `5CEBA4U19C8`.
Results: `tmp/cyclonev_blockmux_fuzz/results.json` (regenerable, not committed).

## Scope actually run

- One mux: `gpio.drive_strength` (`m`, span 4, bcount 20; variants `X`=0 and `x`=1).
- Issue asked for 3-5 GPIO `m`/`n` muxes. Only one was attempted; see
  "Muxes not reached" below.
- Knob: `set_instance_assignment IO_STANDARD` + `CURRENT_STRENGTH_NEW`.
- Verdict = name decoded by `mistral-cv decomp` for the target pin, compared with
  the requested name.

## Results (Quartus 25.1, 2026-10-23)

| | count |
|---|---|
| Named values (variant tables) | 91 (`X`) / 92 (`x`) |
| Distinct names MATCH on PIN_F8 | 43 |
| Distinct names MATCH on other pins (T13, T22, R6, A18; `v3p0_lvttl_8ma`, `v3p3_lvttl_8ma`) | 8 of 8 |
| MISMATCH | 0 |
| INCONCLUSIVE (Quartus rejected the setting) | 21 |
| Control (no strength assignment) decodes to | `v2p5_50ohm` |

The control shows the default is not one of the tested values, so the
MATCHes are not the default coinciding.

### Matched (decoded name == requested)

- LVTTL / LVCMOS / 1.x-2.5 V CMOS: `v3p0_lvttl_{4,8,12,16}ma`,
  `v3p3_lvttl_{4,8}ma`, `v3p0_lvcmos_{4,8,12,16}ma`, `v1p2_{2..8}ma`,
  `v1p5_{2..12}ma`, `v1p8_{2..12}ma`, `v2p5_{4,8,12,16}ma`.
- SSTL: `sstl15_{4,6,8,10,12}ma`, `sstl18_{4,6,8,10,12}ma`,
  `sstl2_{8,10,12}ma`. `sstl15_8ma` and `sstl2_8ma` were the first SSTL probes.

### Rejected by Quartus (INCONCLUSIVE, not a Mistral result)

- `hstl12_*`, `hstl15_*`, `hstl18_*` (18 names): `Error (15716): Pin q is missing an
  I/O standard assignment`. The IO-standard strings I guessed (`HSTL-nn Class I`) are
  not Quartus names. Correct strings not found.
- `sstl15_16ma`, `sstl18_16ma`, `sstl2_16ma`: `Error (169055): Current Strength logic
  option ... not supported by I/O standard`.

### Not attempted (no Quartus knob mapped)

- `off`, `prog_gnd`, `prog_pwr`, `lvds_1r`, `lvds_3r`, `v3p0_pci_pcix`.
- Two combined names: `v3p3_lvttl_8ma_lvcmos_2ma`, `v3p3_lvttl_16ma_lvcmos_2ma`.
- 21 `*_ohm` names (on-chip series/parallel termination).
  - The QSF names I tried (`SERIES_TERMINATION`, `SERIES_TERMINATION_CONTROL`,
    `PARALLEL_TERMINATION`, `PARALLEL_TERMINATION_CONTROL`) are all rejected at
    QSF parse (`Error (125048)`). The OCT assignment name is not identified.

## Pin / variant caveat

- Every MATCH decoded on span `.2`, in tiles `GPIO.018.045`, `GPIO.042.045`,
  `GPIO.011.000`, `GPIO.034.000`, `GPIO.054.016`.
- `v3p3_lvttl_8ma` exists only in the `x` table and matched on all 5 pins, so those
  pins decoded through the `x` table.
- The `X` table (variant 0) is NOT exercised. No pin tested so far was in variant 0.
  The variant is picked from pram bit 24 of each pin; the pin for it is not yet found.

## Limit of the check

- `mistral-cv decomp` prints a decoded name for `m` muxes, not the raw PRAM bits.
- A MATCH therefore verifies that the bits at `cv_block_muxes.bits` equal the claimed
  mask, via Mistral's exact-match lookup, for the value Quartus was asked to set.
- It does not verify the raw bit values independently. Raw-bit dump would need a
  mistral-cv change (out of this session).
- Hand spot-check: `tmp/cyclonev_blockmux_fuzz/gpio_drive_strength_v3p3_lvttl_8ma_pin_t13/*.bt`
  line 16: `s GPIO.034.000:DRIVE_STRENGTH.2 V3P3_LVTTL_8MA ; T13`.
  `..._v1p8_2ma/...bt` line 18: `s GPIO.018.045:DRIVE_STRENGTH.2 V1P8_2MA ; F8`.
  Both agree with the script's parse.

## Muxes not reached (of the 3-5 asked)

- `vod_level`, `vos_level`, `termination_mode`, `termination_control`, `iocsr_std`,
  `pll_select`, `tx_enable_hc`, `output_duty_cycle_delay_ps`: no knob found.
  - `termination_*` needs the OCT names above.
  - `output_duty_cycle_delay_ps` and LVDS `vod`/`vos` knobs not searched.

## Scope of the other block files (issue #103)

Row counts from `cv_block_muxes`. "Die" = whether the e50f die has data for it.

- `opt` (19 rows, oram): tested, see "opt" below.
- `m10k` (76 rows, cram): tested, see "m10k" below.
- `lab` (56), `mlab` (61): tested, see "lab / mlab" below.
- `dsp` (60): MODE values covered by `cyclonev_dsp_fuzz.py`. Input/coef muxes
  remain. Cross-reference, not a duplicate.
- `cmuxcr` (10), `cmuxvr`/`cmuxvg` (5/16), `cmuxhr`/`cmuxhg` (10/31): clock-network
  muxes. Needs global-signal assignments. Medium-hard.
- `dll` (19), `dqs16` (127): DLL/DQS delay. Needs DDR IP. Hard.
- `fpll` (141): mostly `b`/`r` (no named values to verify). `cyclonev_fpll_fuzz.py`
  covers M/N.
- `lvl` (16): level shifter, IO-standard related. Unexplored.
- `term` (22): termination. Blocked on OCT assignment names.
- `hmc` (147): hard memory controller. Present on e50f (`e50f-hmc.txt`). Needs EMIF
  IP. Hard, defer.
- `hip` (244): PCIe hard IP. No `hip` data for e50f. N/A on this die.
- `hssi` (177), `pma3` (137), `pma3c` (2): transceivers. No transceiver data for e50f
  (grep of `e50f-*.txt` finds none). N/A on this die.
- `hps_clocks` (1): HPS. No HPS on this non-SoC die. N/A.
- `serpar` (1): single row, not investigated.
- `cbuf` (14): `b`/`r` only, no named values. Nothing to check.
- `opt` is in `LOAD_CALLS`, so the import is 22 files, not the 21 in the issue text.

## opt (oram) -- 2026-10-23, Quartus 25.1, 5CEBA4U19C8

Run: `scripts/cyclonev_blockmux_fuzz.py --dump-target opt --all`. One default build
plus one build per knob. Mistral's `o` lines print RAW values, and only for
non-default bits, so an absent line means "default".

Data shape: 2 `n`, 10 `b`, 7 `r` rows (not "m/n" as the issue text says).

| verdict | count | rows |
|---|---|---|
| MATCH | 5 | `jtag_id`, `retry_config_on_error_en`, `oct_done_dis`, `nceo_dis`, `allow_device_wide_output_enable_dis` |
| MISMATCH | 3 | `device_wide_reset_en`, `cvp_conf_done_en`, `release_clears_before_tristates_dis` |
| INCONCLUSIVE, setting accepted but `.rbf` byte-identical to default | 3 | `compression_dis`, `crc_error_detection_en`, `external_clk_spi` |
| INCONCLUSIVE, knob applied, no expectation | 1 | `start_up_clock` (`USER_START_UP_CLOCK On`: no bit change) |
| INCONCLUSIVE, no Quartus knob found / tried | 7 | `idcode`, `crc_divide_order`, `drive_strength`, `cvpcie_mode`, `iocsr_ready_from_csr_done_en`, `opt_a`, `opt_b` |

- MATCH evidence:
  - `jtag_id` = Quartus assembler `JTAG usercode` in every build (11 probe builds
    + the run). `USE_CHECKSUM_AS_USERCODE Off` -> `0xFFFFFFFF` on both sides.
  - `retry_config_on_error_en`: `AUTO_RESTART_CONFIGURATION Off` -> `o RETRY_CONFIG_ON_ERROR_EN 0`.
    Asm report: "Auto-restart configuration after error  Off".
  - `oct_done_dis`: `ENABLE_OCT_DONE On` -> `o OCT_DONE_DIS 0`. Asm report: "Enable OCT_DONE On".
  - `nceo_dis`: `ENABLE_NCEO_OUTPUT On` -> `o NCEO_DIS 0`.
  - `allow_device_wide_output_enable_dis`: `ENABLE_DEVICE_WIDE_OE On` -> `o ALLOW_..._DIS 0`.
    Bit 6.5 is also claimed by `start_up_clock` (see overlap below).
- MISMATCH evidence:
  - `release_clears_before_tristates_dis`: `RELEASE_CLEARS_BEFORE_TRI_STATES On` -> the
    printed line is `o CVP_CONF_DONE_EN 0` (bit 6.2), `release_clears...` stays at 1 (bit 6.3).
    `.rbf` differs by 3 bytes. Either 6.2/6.3 labels are swapped in `opt-mux.txt`, or the
    Quartus setting drives 6.2. Labels are wrong on one of the two readings.
  - `cvp_conf_done_en`: default build (`ENABLE_CVP_CONFDONE` Off) decodes 1, name predicts 0.
    On-build still 1; the `.rbf` changes (93 bytes) somewhere else. Bit 6.2 is not the
    `ENABLE_CVP_CONFDONE` bit.
  - `device_wide_reset_en`: `ENABLE_DEVICE_WIDE_RESET On` -> `o DEVICE_WIDE_RESET_EN 0`;
    default -> 1. Polarity is inverted against the name. Bit 6.4 is also claimed by
    `start_up_clock` bit 3 (knob build `START_UP_CLOCK 37`, default `3f`).
- Table overlap (opt-mux.txt): two fields claim one bit each.
  - 6.4: `device_wide_reset_en` and `start_up_clock` bit 3.
  - 6.5: `allow_device_wide_output_enable_dis` and `start_up_clock` bit 4.
- INCONCLUSIVE, bitstream unchanged:
  - `COMPRESSION_MODE On`: asm report says "Compression mode On", `.rbf` identical to default.
  - `CRC_ERROR_CHECKING On`: `.rbf` identical; setting not in the asm settings table.
  - `CLOCK_SOURCE External` + `CONFIGURATION_CLOCK_FREQUENCY "25 MHz"`: asm applied it
    (`EXTERNAL`, `25 MHZ`); `.rbf` identical; `external_clk_spi` stays 100.
- Rejected by Quartus (not counted as a Mistral result):
  - `CVP_MODE Auto` (Error 125036). Legal value not identified.
  - `DEVICE_INITIALIZATION_CLOCK CLKUSR` (Error 125036).
- Not attempted: names for `idcode`, `crc_divide_order`, `drive_strength`, `cvpcie_mode`,
  `iocsr_ready_from_csr_done_en`, `opt_a`, `opt_b`. `opt_b` prints `ffffff40.2dffffff` in every build.
- Caveat: default-side verdicts depend on an absent line meaning default. Mistral prints nothing
  for a default value, so absence cannot distinguish "default" from "not decoded".

## m10k (cram) -- 2026-10-23, Quartus 25.1, 5CEBA4U19C8

Run: `scripts/cyclonev_blockmux_fuzz.py --dump-target m10k --all`. Styles x widths
(1/2/5/10/20/40, depths 8192/4096/2048/1024/512/256), `(* ramstyle = "M10K" *)` for
inferred styles, ports left unplaced:

- `sp`: single-port, inferred.
- `sdp`: simple dual-port, inferred.
- `tdp`: true dual-port, inferred. Flattens to logic (see TDP below).
- `tdpip`: true dual-port, explicit `altsyncram` BIDIR_DUAL_PORT.

Checked muxes (expected = the RAM style's width/mode):

| mux | sp | sdp | tdpip |
|---|---|---|---|
| `a_data_width` | 6/6 MATCH | 6/6 MATCH | 5 MATCH, 1 MISMATCH (W=40) |
| `b_data_width` | not checked (port unused) | 6/6 MATCH | 5 MATCH, 1 MISMATCH (W=40) |
| `true_dual_port` (`b`) | 6/6 MATCH (=0) | 6/6 MATCH (=0) | 6/6 MATCH (=1) |

- `tdp` (inferred TDP): 0 M10K tiles. All 18 `tdp` checks are INCONCLUSIVE.

Observed-only muxes (no Quartus knob; INCONCLUSIVE, decoded values recorded in `results.json`):

- `a/b_fast_write`, `a/b_outclr_en`, `a/b_output_sel`.
- `sp`/`sdp`: `slow`, `off`, `async` in every design.
- `tdpip`: fast_write `FAST` (explicit megafunction) vs `SLOW` (inferred). Different RAM
  construction gives different write mode; still not verdict-ed.

Caveats:

- `a_data_width` = 40 is not a printed-line match. Mistral's default A width is 40, and
  Mistral never prints a default, so the A=40 result is "absent = default". The
  `b_data_width` = 40 line *is* printed. A=40 can only ever be seen as absence.
- Observed only, no Quartus knob (INCONCLUSIVE): `a/b_fast_write`, `a/b_outclr_en`,
  `a/b_output_sel`. Decoded `slow`, `off`, `async` in every design. The Verilog registers
  the read data, but Quartus did not put the output register into the M10K (`output_sel` stayed `async`).
- Other printed `b` flags (`A/B_DATA_FLOW_THRU 1`, `DISABLE_UNUSED 0`): not verdict-ed.
- `top_*_sel` / `bot_*_sel` (22 `n` rows): never printed (all default), no knob. Not tested.
- Mistral `RAM.N` lines carry the RAM init content (`ff.ffffffff`). Not checked.

### TDP fit time (measured, 2026-10-23 18:07-18:09)

- First pass used the 60 s fit limit shared with SP/SDP. Every TDP fit hit it (`TIMEOUT`,
  logged, INCONCLUSIVE). This was a limit that was too low, not a hung fit.
- Uncapped `quartus_fit` on `m10k_tdp_w1`: 147.2 s wall (`tmp/logs/tdp_fit_timing.log`),
  host loadavg 15-17 (shared host, other Quartus jobs running).
- Inferred `tdp` limit set to 450 s (3x that one sample, rounded). One sample only.
- The inferred-`tdp` rerun was stopped after W=1 (flattened, see below). The `tdpip` runs
  used the 60 s limit; their fits took 9-15 s.

### TDP: inferred vs explicit

- Inferred `tdp` (two always blocks, one memory array): Quartus flattens it to logic,
  `Total block memory bits 0`, ~22k ALUTs / 8k registers at W=1 (map report,
  `tmp/cyclonev_blockmux_fuzz/m10k_tdp_w1/`). No M10K tile decodes. Run 2 was stopped after
  W=1, so W=2..40 of the inferred idiom were not re-run. Run 1 (60 s limit) timed out on all six.
  Result: 6 INCONCLUSIVE per check for `tdp`, none is a Mistral result.
- Explicit `tdpip` (`altsyncram`, `operation_mode BIDIR_DUAL_PORT`, `ram_block_type M10K`,
  `clock1` tied to `clk`): maps to M10K (`Total block memory bits 10240` at W=20).
  Quartus accepted it after two fixes (`clock1` must be connected; `clear box` error otherwise).

| check | W=1 | W=2 | W=5 | W=10 | W=20 | W=40 |
|---|---|---|---|---|---|---|
| `true_dual_port` = 1 | MATCH | MATCH | MATCH | MATCH | MATCH | MATCH (2 tiles) |
| `a_data_width` | MATCH | MATCH | MATCH | MATCH | MATCH | MISMATCH |
| `b_data_width` | MATCH | MATCH | MATCH | MATCH | MATCH | MISMATCH |

- W=40 MISMATCH: two M10K tiles (`M10K.022.002`, `M10K.046.021`), each decoding
  `A/B_DATA_WIDTH 20`. Per-tile widths sum to 40, which suggests Quartus splits the x40
  TDP across two x20 blocks. This is an inference from the decode, not checked against
  Intel's M10K mode table in this session. Recorded as MISMATCH against the one-tile
  expectation; not counted as a Mistral failure.
- Caveat for the `a=40` results in SP/SDP: `A_DATA_WIDTH 40` is absent (default), so those
  are absence matches. `B_DATA_WIDTH 40` is printed (non-default) in SP and SDP.

## lab / mlab -- 2026-10-23, Quartus 25.1, 5CEBA4U19C8

Run: `--dump-target lab --all` and `--dump-target mlab --all`. Probes in `LAB_PROBES`,
checks in `LAB_CHECKS` (`scripts/cyclonev_blockmux_fuzz.py`). Each check states its
basis; `distinct` checks are relational (no value name is established).

Method:
- Registers pinned with `set_location_assignment LAB_Xa_Yb -to <reg>`. Decoded tile
  is `LAB.a.b` (verified on LAB_X10_Y10 and LAB_X20_Y20).
- `LABCELL_*` on a register is rejected (Error 171011). `LAB_*` on a register works.
- Three clocks pinned to one LAB fail to fit (Error 170071). Unpinned, the third clock
  lands in a different LAB, so clk2 is not reached.
- Slot is chosen by the fitter. Checks read it from the FF routing line
  (`r LAB.a.b.S:FFT0`).
- Logic pinned with `(* keep *)` wires lands in another LAB for sclr/sload/en.
  Enable is LUT feedback; LAB `EN0_EN` stays 0 with and without an enable.
- Control: one posedge FF (`ctrl`). MLAB control is the idle MLAB tile in the same .bt.
- Probes: ctrl, negclk, clk2, clk3, sclr, sload, en, mlab_ram (16x1, ramstyle MLAB).

Counts, by row (`cv_block_muxes`, one verdict per row):

| target | rows | MATCH | MISMATCH | INCONCLUSIVE |
|---|---|---|---|---|
| lab | 56 | 3 | 1 | 52 |
| mlab | 61 | 5 | 0 | 56 |

Checks (lab 14, mlab 12):
- lab MATCH: `tsclr_dis` (ctrl, clk2), `en0_en` (ctrl), `tclk_sel` (clk2, relational).
- mlab MATCH: `ram_dis` (RAM 0, idle 1), `write_en` (RAM 1, idle 0), `sclr_dis` (RAM 1),
  `tmode` and `bmode` (RAM in all 10 slots), each from the mlab_ram probe unless noted.
- Raw .bt lines checked by hand (`tmp/cyclonev_blockmux_fuzz/labdump_*/`):
  - `s LAB.020.020:TSCLR_DIS.0 1` (ctrl).
  - `s LAB.020.020:TCLK_SEL.0 CLK0` and `TCLK_SEL.1 CLK1` (clk2).
  - `s MLAB.013.001:RAM_DIS 0`, `TMODE.0 RAM`, `WRITE_EN 1` (mlab_ram).

### MISMATCH

- `clk0_inv`, control (`ctrl`, posedge FF, no inversion requested).
  - Expected 0 (Mistral default, `cv_block_muxes` g row).
  - Decoded `s LAB.020.020:CLK0_INV 1`.
  - The negedge probe also decodes `CLK0_INV 1`, with `CLK0_SEL CLKB` added. So the
    bit is 1 for both polarities. Not established: whether the bit means "not inverted"
    in silicon (naming wrong) or is unrelated to clock polarity. Verdict is MISMATCH
    against the naive expectation only.

### Observed only (INCONCLUSIVE, decoded value recorded in results.json)

- `clk0_sel`: negedge decodes `CLKB`. clka/clkb polarity not established.
- `clka_sel`: `cin0` (ctrl), `din0` (clk2). Source depends on fitter routing.
- `clkb_sel`: `din1` in ctrl and negedge. Unused, no fixed expectation.
- `aclr0_sel`: `ACLR0` printed with no clear. Not discriminating.
- `tmode` (ctrl): `e_0` for one top FF. Mode meaning not established.
- `tclk_sel` (clk3): `off` in the probed slot. Clk2 not reached.
- `tsclr_dis` (sclr): `1` in the FF's LAB. Sync clear is LUT logic in another LAB.
- `sload_sel` (sload): `din1`. No LAB-level change.
- `en0_en` (en): `0`. Enable is LUT feedback, not LAB EN0.
- mlab: `mcrg_voltage` `VCCL`; `write_pulse_length` `650`; `clka_sel` `gin2`;
  `tclk_sel` slot 5 `CLK2`; `t_feedback_sel` all 10 slots `1`.

### Not reached

- lab, all rows: the `b`-half of every i row (only top FF slots probed); `tclr_sel`,
  `tef_sel`, `tpkreg*`, `en1/2_*`, `clk1/2_inv`, `sclr_*`, `sload_*`, `aclr*_inv`,
  `dft_mode`, `regscan_latch_en`, `bypass_dis`, `tto/bto_dis`.
  - Reason: no probe changes these, or the LUT-based forms of these controls land in
    another LAB.
- `tclk_sel = clk2` in a LAB: a third clock needs a LAB the fitter did not give.
- `write_pulse_length` 500/800/950 and `mcrg/maddg` `vcchg`: no design variant tried.
- `lut_mask`: out of scope (lifter exercises it).

## lab second pass -- 2026-10-23, Quartus 25.1, 5CEBA4U19C8

Run: `--dump-target lab --all`. Probes `bank_*` in `BANK_PROBE_SPECS`; checks in `LAB_CHECKS`
(`moved` = differs from `bank_plain` at every span; `ffb`/`fft`/`ffall` = FF-occupied slots).

Counts (`cv_block_muxes`, one verdict per row; a row with any MISMATCH is MISMATCH):

| target | before (first pass) | after (second pass) |
|---|---|---|
| lab | 56: MATCH 3, MISMATCH 1, INCONCLUSIVE 52 | 56: MATCH 7, MISMATCH 6, INCONCLUSIVE 43 |
| mlab | 61: MATCH 5, MISMATCH 0, INCONCLUSIVE 56 | not re-run this pass (baseline re-confirmed) |

- Every bank landed in `LAB.020.020` with FFs in all 10 slots (top `FFT<n>` and bottom `FFB<n>` routing lines).
- Control: `bank_plain` (16 posedge FFs, nothing shared except the clock).
- Single-FF `ctrl`/`negclk` probes still print `CLK0_INV 1`.

### Results by probe

| probe | shared control | rows that moved vs control | notes |
|---|---|---|---|
| `bank_en` | enable (16) | `EN0_EN` (ctrl `0` -> absent=default `1`), `EN0_NINV` (default `1` -> `0`) | MATCH on `en0_en` is by absence |
| `bank_en2` | two enables (10+10) | `EN0_EN` as above; `EN1_NINV` default `1` -> `0` | no `EN1_EN` line in either build |
| `bank_sclr` | sync clear (16) | `TSCLR_DIS` `1` -> `0` on every top FF slot; `BSCLR_DIS` `1` -> `0` on every bottom FF slot | `SCLR_SEL DIN1`, `SLOAD_EN 0` |
| `bank_sload` | sync load (16) | `TSLOAD_EN` `0` -> `1` on every top FF slot; `BSLOAD_EN` `0` -> `1` on bottom | `SLOAD_SEL DIN2` |
| `bank_aclr` | async clear (16) | `ACLR0_INV` `0` -> `1`; `ACLR0_SEL` ctrl `ACLR0` -> absent (default `din3`) | |
| `bank_clr2` | two async clears (10+10) | `ACLR0_INV 1`, `ACLR1_INV 1`; `ACLR0_SEL`/`ACLR1_SEL` absent (default `din3`/`din2`) | |
| `bank_pn` | posedge 10 + negedge 6 | `CLK0_INV` absent (0); `CLK0_SEL` absent (`clka`); `CLK1_SEL CLKB` | per-slot `TCLK_SEL`/`BCLK_SEL` show CLK0 and CLK1 |

Raw `.bt` lines checked by hand (`tmp/cyclonev_blockmux_fuzz/labdump_bank_*/`):
- `bank_sclr`: `s LAB.020.020:TSCLR_DIS.6 1` and `.8 1` only. Top FF slots 0-5, 7, 9 have no
  line, so they decode the default 0. Slots 6 and 8 hold bottom FFs only (`r LAB.020.020.6:FFB0`).
- `bank_sload`: `TSLOAD_EN.0-5,7,9 1`, no line at 6 and 8. Same set as the top FF slots.
- `bank_clr2`: `s LAB.020.020:ACLR0_INV 1`, `s LAB.020.020:ACLR1_INV 1`; no `ACLR*_SEL` line.
- `bank_en`: `s LAB.020.020:EN0_NINV 0`; no `EN0_EN` line.

### MISMATCH (against the naive expectation, not established as Mistral error)

- `clk0_inv` (ctrl, from first pass): `s LAB.020.020:CLK0_INV 1`, expected `0`.
  - Single FFs print `CLK0_INV 1` for posedge (`ctrl`) and negedge (`negclk`).
  - 16-FF posedge bank (`bank_plain`) and posedge+negedge mix (`bank_pn`) print no `CLK0_INV` line.
  - So the bit does not track FF polarity in these builds. Not established what it means.
- `en0_ninv` (`bank_en`): `s LAB.020.020:EN0_NINV 0`, expected `1` (not inverted, Mistral default).
  The flip 1 -> 0 happens in exactly the enable builds. Polarity meaning not established.
- `en1_ninv` (`bank_en2`): `s LAB.020.020:EN1_NINV 0`, expected `1`. Same pattern as EN0.
- `aclr0_inv` (`bank_aclr`): `s LAB.020.020:ACLR0_INV 1`, expected `0`. Row also MATCHes on `bank_clr2`
  (`moved`, `ACLR0_INV 1`). The row is MISMATCH because any MISMATCH wins.
- `aclr0_sel` (`bank_aclr`, `bank_clr2`), `aclr1_sel` (`bank_clr2`): no `*_SEL` line, so default
  `din3`/`din2`. Naive expectation was `aclr0`/`aclr1` (the clear used). Not what decodes; the
  `*_INV 1` bits are what moves.

### Observed only (INCONCLUSIVE)

- `clk0_sel`: `CLKB` on the negedge single FF (`negclk`), absent (`clka`) on `bank_pn`.
- `CLK1_SEL CLKB` appears in `bank_pn` only; the negedge single FF selects it on `CLK0_SEL`.
  Not checked per FF which clock index the negedge bank uses.
- `tclk_sel` / `bclk_sel` per slot in `bank_pn`: CLK0 and CLK1 mixed. Not mapped to FF polarity.

### Not reached

- `en1_en`: never printed, `EN1_NINV` carries the only visible change for bank B.
- `sclr_dis`, `sload_en`: observed `0` / `1`, no independent expectation.
- Any `clr`/`sclr` LUT-logic form in another LAB: not re-probed this pass.
- `tclk_sel = clk2` on a bank (clk3 probe): still not reached (first-pass reason unchanged).

## cmux (clock-network muxes) -- 2026-10-23, Quartus 25.1, 5CEBA4U19C8

Run: `--dump-target cmux --all`. Probes in `CMUX_PROBES`, checks in `CMUX_PRESENCE`.
- Each probe drives 8 FFs per clock pin. Clock pins from `eda/ibis/5ceba4_u4840.xml`:
  K7 (8A CLK_0), G10 (8A CLK_1), P9 (3B CLK_0), H10 (7A CLK_2), T15 (4A CLK_3), L17 (5B CLK_2).
  F8 is a general user I/O.
- Promotion knob: `set_instance_assignment -name GLOBAL_SIGNAL "<GLOBAL CLOCK|REGIONAL CLOCK|OFF>"`.
- Mistral prints non-default config only. Verdicts use the presence of a `CMUX<block>` line
  (config `s` or routing `r`). Assumption: a selected block always prints its `INPUT_SEL`, since
  every printed value differs from the row default.

CMUX blocks in each probe (`.bt` lines):

| probe | clock pin | setting | blocks present |
|---|---|---|---|
| `cm_ded` | K7 | none | CMUXVG.025.045 |
| `cm_glob` | K7 | GLOBAL CLOCK | CMUXVG.025.045 |
| `cm_reg` | K7 | REGIONAL CLOCK | CMUXVR.025.045 (CMUXVG absent) |
| `cm_off` | K7 | OFF | none |
| `cm_gen` | F8 (general I/O) | none | CMUXVG.025.045 (routing `TDMUX.026.045.0012 -> CMUXVG:CLKIN.2`) |
| `cm_h10` | H10 (7A) | none | CMUXVG.025.045 |
| `cm_t15` | T15 (4A) | none | CMUXVG.021.000 |
| `cm_p9` | P9 (3B) | none | CMUXVG.021.000 |
| `cm_2ded` | K7 + G10 | none | CMUXVG.025.045 (INPUT_SEL.1 and .3) |
| `cm_l17` | L17 (5B) | none | CMUXHG.054.022 |
| `cm_l17_glob` | L17 | GLOBAL CLOCK | CMUXHG.054.022 |
| `cm_l17_reg` | L17 | REGIONAL CLOCK | CMUXCR.054.002 (no CMUXHR, no CMUXHG) |

Counts (`cv_block_muxes`, one verdict per row). Before this pass: no cmux probe existed, all 72 rows INCONCLUSIVE.

| target | rows | MATCH | MISMATCH | INCONCLUSIVE |
|---|---|---|---|---|
| cmuxcr | 10 | 0 | 0 | 10 |
| cmuxvr | 5 | 1 | 0 | 4 |
| cmuxvg | 16 | 1 | 0 | 15 |
| cmuxhr | 10 | 0 | 1 | 9 |
| cmuxhg | 31 | 1 | 0 | 30 |

Checks (10 presence checks: 8 MATCH, 1 MISMATCH, 1 INCONCLUSIVE):
- MATCH `cmuxvr.input_sel`: REGIONAL on a vertical pin selects CMUXVR; GLOBAL does not.
- MATCH `cmuxvg.input_sel`: default and GLOBAL select CMUXVG; REGIONAL does not.
- MATCH `cmuxhg.input_sel`: 5B pin default and GLOBAL select CMUXHG; REGIONAL does not.
- MISMATCH `cmuxhr.input_sel` (against the name-based expectation only): L17 with REGIONAL CLOCK
  gives no CMUXHR. The clock goes through CMUXCR.054.002 instead (`s CMUXCR.054.002:INPUT_SEL.5 8`).
  Not established that CMUXHR is wrong: it may serve other pins that this pass did not probe.
- INCONCLUSIVE `cmuxcr.input_sel`: presence only, no naming-based expectation.

Raw `.bt` lines checked by hand (`tmp/cyclonev_blockmux_fuzz/cmux_cm_*/`):
- `cm_reg`: `s CMUXVR.025.045:INPUT_SEL.4 6`; the file has no `CMUXVG` line.
- `cm_glob`: `s CMUXVG.025.045:INPUT_SEL.2 00`; `cm_reg` has no `CMUXVG` line.
- `cm_l17_glob`: `s CMUXHG.054.022:INPUT_SEL.0 02`; `cm_l17_reg` has no `CMUXHG` line.

Observed only (INCONCLUSIVE):
- `cmuxhg.clkpin_sel_2`: value 5 in `cm_l17` (span 2) and `cm_l17_glob` (span 0).
- `cmuxcr.clkpin_sel_0`: value 2 in `cm_l17_reg` (span 5).
- `cmuxhg.testsyn_enout_select`: `PRE_SYNENB` at spans 2 and 0.

Not reached:
- `cmuxhr.clkpin_sel` / `nclkpin_sel` and `cmuxvr`/`cmuxvg`/`cmuxhg` `clkpin_sel`: no probe printed
  them. Pin-index to field mapping not established.
- `enable_register_mode`, `enable_register_power_up`: no Quartus knob identified for the clock-network
  enable register.
- `pll_feedback_enable_*`, `feedback_driver_select_*`, `burst_*`, `dynamic_clk_select`,
  `testsyn_enout_select` as a verdict: need a PLL or DDR/DQS design, not built.
- `cmuxhr` input_sel for other pins: not probed.

## dsp (input / coefficient / register / output muxes) -- 2026-10-23, Quartus 25.1, 5CEBA4U19C8

Run: `--dump-target dsp --all`. Probes in `DSP_PROBES`, checks in `DSP_CHECKS`. MODE excluded
(covered by `cyclonev_dsp_fuzz.py`). Verdict = printed value or Mistral default on the DSP tile
with the most printed settings.

Counts (`cv_block_muxes`, 60 rows): before 60 INCONCLUSIVE (no dsp probe); after MATCH 4,
MISMATCH 6, INCONCLUSIVE 50.

Probes (one DSP each, plain Verilog unless noted): `u_comb`, `u_reg`, `s_reg`, `w9_reg`
(9x9 signed), `inreg`, `inout`, `coef_const` (`a * 18'sd11111`), `coef_sig`, `preadd`
(`(a+b)*c`, no pre-adder inferred), `en_reg`, `acc`, `sub`, `chain`, `preadd_ip` (megafunction).

MISMATCH (against name-based expectation):
- `ax_signed`, `ay_signed` (probe `s_reg`, 18x18 both operands signed): decoded 0, expected 1.
  `s_reg/dsp_s_reg.bt` has `s DSP.033.001:BX_SIGNED 1` and `BY_SIGNED 1`, no AX/AY line.
  Same flags on 9x9 (`w9_reg/dsp_w9_reg.bt:203-204`: `AX_SIGNED 1`, `AY_SIGNED 1`) and
  `acc`/`sub`/`coef_const`/`coef_sig` (18x18 signed) print no AX/AY. Mistral's AX/AY
  mapping for 18x18 or the A-operand sign field is not established.
- `dec_inv`, `preload_inv`, `acc_inv`, `sub_inv` (probe `u_reg`, no inversion requested):
  decoded 1, expected 0. Each prints `1` in all 10 probes, including unsigned comb
  (`u_comb/dsp_u_comb.bt:456` `DEC_INV 1`). DATA_INV prints `1ff` in the same probes.
  Whether 1 means "not inverted" in silicon is not established.

MATCH: `bx_signed`, `by_signed` (signed 18x18 and unsigned), `oreg_ctrl` (REG when registered,
`bypass` absent when not, `inout` REG), `preadder_en` (absent, default 0, on `u_reg` only).

Observed only (INCONCLUSIVE), printed values recorded in `results.json`:
- Input registers: `s_reg` none; `inreg` prints `INREG_CTRL_BX/BY/BZ REG` only. The A operand
  register is not printed although the map report shows 36 dedicated logic registers (not
  packed into the DSP). `inreg_ctrl_ax/ay/az` unresolved.
- Coefficient rows `coef_a`/`coef_b` (raw `r`, 8 spans): no `COEF_*` line in any probe,
  including the constant and signal coefficient probes. Not reached.
- `preadder_en`: `preadd` (plain Verilog) maps `(a+b)` to ALUTs (map: 37 ALUTs, 2 DSPs), no
  pre-adder flag. `preadd_ip` (`altera_mult_add`, `preadder_mode("SIMPLE")`,
  `preadder_direction_0("ADD")`) fails in quartus_map: `Error (272006): Illegal parameter
  value: dataa port is not instantiated` and an internal assertion
  (`cbx_altera_mult_add.cpp:1113`). Port names not resolved. Not reached.
- `enable0_inv`, `enable0_force`: `en_reg` prints no enable field.
- Clock selects `clk*_sel`, `aclr*_sel`, `clk_*_sel`: printed (`CLK0_SEL 3`, `ACLR0_SEL 2`,
  `CLK_AX17_SEL 2`), no independent expectation.
- `data_inv` (raw): `1ff`/`0ff` vary by probe (`s_reg` DATA_INV.5 `0ff`), no expectation.

Not reached: `cascade_*`, `chain_output_en`, `delay_cascade_*`, `systolic_reg_en`,
`double_acc_en`, `partial_reconfig_en`, `dft_*`, `load_value`, `idireg_*` except acc/sub,
`cascade_1st_en`, `dec/acc/preload/sub` inversion as true (not requested in any probe).

## gpio termination / LVDS / variant X -- see section below (in progress)

## lvl -- see section below (in progress)

## Not done

- Other GPIO `m`/`n` muxes (see above).
- Raw-bit verification (needs a mistral-cv change).
- OCT / termination knob (needs the correct QSF names).
- opt: `start_up_clock`, `external_clk_spi`, `crc_error_detection_en`, `compression_dis`
  need a different Quartus knob or a bitstream-visible setting.
- m10k: output-register and fast-write knobs; `top/bot` selects.
