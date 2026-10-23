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

- `opt` (19 rows, oram): global config options (start-up clock, etc.). Quartus
  global settings via QSF. Untested. Promising next.
- `m10k` (76 rows, cram): RAM modes/widths. Quartus RAM inference with port
  widths and `ram_style`. Medium. Largest named-value set after GPIO.
- `lab` (56), `mlab` (61): LAB clock/enable/clear selects. Needs FF enable/clear
  source designs. Medium-hard.
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

## Not done

- Other GPIO `m`/`n` muxes (see above).
- Raw-bit verification (needs a mistral-cv change).
- OCT / termination knob (needs the correct QSF names).
