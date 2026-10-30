# Cyclone IV GX FF controls, clock sources, carry-in (#165, 2026-10-30)

Code: `lifters/cycloneiv_clean/ffctl.py` (FfCtl), used by `emit.py` (`Builder._ff_controls`). Check: `scripts/cycloneiv_clean_ffctl_check.py`. Test: `tests/cycloneiv_clean/test_ffctl.py`.
Conditions: EP4CGX150, Quartus 25.1 asmdb, corpus `corpus/cycloneiv`, static analysis (libcomp_asm decompile via snapshot `ctl_decode`) + existing builds only (0 new builds).

## Value law
- `ASMDB_ARCH_GROUP_STD::select`: every bit of a mux entry is inverted when its `arch_value` is 0 (law from `docs/cycloneiv-clean-io.md`; `asmdb_select.std_select`).
- `arch_value` 0 groups of the LAB: `LE_CLOCK_SELECT`, `LE_CLEAR_SELECT`, `LE_USE_CARRY`, `LAB_ENABLE_CE` gi 0/1, `LAB_CLR_INVERT_PAIR`, `LAB_INVERT` gi 5. Vendor value = NOT bit.
- Explains three earlier empirical facts: LE_CLOCK_SELECT bit 1 = mux gi 0, LE_USE_CARRY bit clear = carry, ENABLE_CE bit 0 = enable used.

## LAB signals (vendor writers, libcomp_asm `process_end_of_phase`)
| Signal | Group | Inputs (input number i) | Used when |
|---|---|---|---|
| clock k=0,1 | `LAB_CLOCK_FAST_MUX` gi k (@0x15e138) | 0..3 = LAB_CONTROL_MUX i, 4..9 = BLK_CLK_BUF line i-4 (value = RE index + base) | always |
| aclr k | `LAB_CLEAR_FAST_MUX` gi k (@0x15deba) | 0..3 = LAB_CONTROL_MUX, 4..9 = BLK_CLK_BUF line (shared 6 second-level bits), 10 = none | decoded input != 10 |
| enable k | `LAB_CE_FAST_MUX` gi k (@0x15dd22) | i = LAB_CONTROL_MUX i | `LAB_ENABLE_CE` gi k value 1 (CE index == clock index, `process_atom`@0x15f628) |
| sclr | `LAB_SYNC_CLR_FAST_MUX` (@0x15eb62) | i = LAB_CONTROL_MUX i | `LAB_ENABLE_SYNC_SIGNALS` value 2, 3, 5 |
| sload | `LAB_SYNC_LOAD_FAST_MUX_MAG` (@0x15ec60) | i = LAB_CONTROL_MUX i | value 1, 3; value 4, 5 = sload tied high |
- `LAB_ENABLE_SYNC_SIGNALS` value (`process_atom`@0x15feb6): 1 sload only, 2 sclr only, 3 both, 4 sload = VCC, 5 sload = VCC + sclr; value -> bits through the mux map (3 bits).
- Select decode = inverse of the writer: pattern of `asmdb_select.select(first level, i)` + `(second level, nxt[i])`; most constrained matching input wins (FREE second level = unconstrained).
- RE-type constants in the writers (0x11c, 0xdc, 0xe1, 0x1b0, ...) are CDB_RE types, not `DEV_ELEMENT_ENUM` values (the sclr / sload writers accept only 0x11c as source and GT shows LAB_CONTROL_MUX sources, so 0x11c = LAB_CONTROL_MUX is inferred; the enum has MEDIUM_EAB_BUFFER at 284).
- Shared bits (vendor-declared): `LAB_CLOCK_FAST_MUX` gi 0 second-level bit = `LAB_SYNC_LOAD_FAST_MUX_MAG` bit (LAB_CONTROL_MUX 0/1 pair shared by clock 0, aclr 0, enable 1, sload); gi 1 second-level = pair 2/3 (clock 1, aclr 1, enable 0, sclr).
- Unused `LAB_CLEAR_FAST_MUX` gi reads first-level 00 = "line" when the other gi selects a line (second-level bits shared). `ASM_LE_CLEAR_SELECT::process_atom`@0x16baea gives an idle LE the signal whose real source is NULL: equal line selections of gi 0 and gi 1 = signal 1 unused (`aclr_shared_line`, counted).

## Per LE
- clock / enable group g = value of `LE_CLOCK_SELECT` (= mux gi); aclr group = value of `LE_CLEAR_SELECT`.
- `LE_USE_SYNC_CLEAR` and `LE_USE_SYNC_LOAD` (DECISION mux, value 1 writes the one real bit; both groups write the same bit): bit = sclr term connected OR sload term connected, so a set bit also proves a register exists. LAB state 4 / 5 + bit: sload tied high, D = ASDATA (DATAC input), also when the LE has a LUT.
- `LE_USE_REGISTER_FEEDBACK` (@0x16c294) = 1: the LE's DATAC input is its own register.
- `LE_USE_CARRY` value 1 (bit clear) = carry-in connected. No chain use: carry-in term unconnected, cin = gnd; `cout = lut4(mask, dataa, datab, cin, 0)` in every mode (`cycloneiv_atoms.v`).

## Polarity (read off specimens; the vendor signal-id table, ASM_SINGLE_LAB_MODEL_BASE ctor jump table, is not read)
- `LAB_INVERT` gi k = line k of the vendor `VIRTUAL_LAB_LINE` table (`ASM_LAB_MODEL_TITAN` ctor@0x166e26, 11 lines of 20 bytes at 0x3cda00; field 1 = signal mask 4 clock, 2 enable, 0x40 sload, 8 aclr, 0x20 sclr): 0 clk0, 1 ce0, 2 clk1, 3 ce1, 4 sload, 5 sclr; table lines 5..8 (third clock pair, the two aclr lines) are not LAB_INVERT lines for this die (aclr polarity = LAB_CLR_INVERT_PAIR). Order of lines 0..4 is the table order; gi 5 = sclr (table line 9) is the corpus reading (an inverted-sclr build exists), the builder that drops lines 5..8 (`ASM_SINGLE_LAB_MODEL_BASE` ctor) is not decoded.
- Value 1 = inverted for clocks from a BLK_CLK_BUF line; sources from LAB_CONTROL_MUX flip it (`look_up_signal_polarity`@0x1563ae: xor for source classes in mask 0x1f80). Net result in the netlist sense: clock inverted = value ^ (source is LCM); enable / sload / sclr inverted = NOT value (always LCM sources).
- aclr: `LAB_CLR_INVERT_PAIR` value bit k = polarity of aclr k (`process_end_of_phase`@0x15ee88), inverted = value bit ^ (source is LCM).
- Power-up level: no asmdb group, `ASM_REG_POWER_UP_MONITOR` writes no bits; every corpus dffeas is `power_up = "low"`. Modelled as power-up 0.

## Carry-in source
- `ASM_CARRY_CHAIN_MONITOR_BASIC::validate_chain_le_locations`@0xfb2b6: LE n > 0 <- LE n-1 of the same LAB; LE 0 <- LE 15 of the LAB at Y+1 (same X).
- Family flag `m_chain_skip_half_labs` (LE 8 may chain from LE 15 above): set per `base_family` (6 -> 1, 0xe / 0x10 -> 0, 0x38 -> 1); the family value of Cyclone IV GX is not read. Not modelled: LE 8 <- LE 7.
- No cross-LAB carry link exists in the 16,297 corpus builds (every carry-mode LE has its source in the same LAB, LE n-1; no LE 0 in carry mode): cross-LAB rule is vendor-code only.

## Check results (2026-10-30, EP4CGX150 corpus, existing builds; rules read off ~10 builds of the 16,297)
- `scripts/cycloneiv_clean_ffctl_check.py --stride 60` (272 designs, per GT dffeas / carry-mode LE), matched / missing / extra / wrong:
  - ena 107 / 0 / 0 / 0; aclr 531 / 0 / 0 / 0; sclr 53 / 0 / 0 / 0; sload 129 / 0 / 0 / 0 (incl. sload tied high); clock polarity 1,708 / 0 / 0 / 0; ASDATA 56 / 0 / 0 / 0; carry-in 250 / 0 / 0 / 0.
- Second sample, `--stride 13` (1,254 designs, a different selection of the 16,297): ena 606 / 0 / 0 / 0; aclr 2,445 / 0 / 0 / 0; sclr 246 / 0 / 0 / 0; sload 580 / 0 / 0 / 0; clock polarity 8,127 / 0 / 0 / 0; ASDATA 234 / 0 / 0 / 0; carry-in 1,572 / 0 / 0 / 0.
- Idle agreement (GT idle, emitted idle) is outside the headline: ena 1,601, aclr 1,177, sclr 1,655, sload 1,579.
- Not covered by any specimen: LE 8 chaining from LE 15 of the LAB above (skip-half-LAB family flag); polarity of aclr / clocks from sources other than BLK_CLK_BUF lines and LAB_CONTROL_MUX (global-network inversions through the clock control block).
- Register claims without a clock (image): 1,779 of 38,772 `reg_used` claims selected a LAB clock mux with first level 0000000 (LE_CLOCK_SELECT at its blank default). Vendor: `ASM_LAB_CLOCK_FAST_MUX::process_end_of_phase`@0x15e138 writes the mux of every signal with a source and `ASM_LE_CLOCK_SELECT::process_atom`@0x16ba06 selects it per register, so such a register cannot exist: claims dropped (`ff_claim_dropped_no_clock_source`; sync-bit FFs kept). Corpus: 0 dropped in 1,708 FFs, ff_site stays 1,708 / 0 / 0 / 0. Image: 36,993 FFs, 0 without clock.
- Family: the dstr family-name table is sorted by enum (index - 456 = DEV_FAMILY_ENUM): STINGRAY = 0x30, CYCLONEIVE = 0x11, CUDA (Cyclone III) = 0xe, YEAGER = 0x3d (the YGR monitor / Cyclone V). `base_family` 0x30 is used by `ASM_PLL_MODEL_STINGRAY` and the STINGRAY clock-select classes.
- The LAB model ctor@0x161508 jump table (0x3cd61c) shares one handler for {0xe, 0x30}: Cyclone IV GX uses the Cyclone III (CUDA) LAB model. `ASM_CARRY_CHAIN_MONITOR_BASIC` accepts only 6, 0xe, 0x10, 0x38 (no 0x30), so no monitor class gives a skip flag for IV GX directly; CUDA (0xe) has `m_chain_skip_half_labs` = 0, taken for IV GX (same LAB model). Corpus: LE 8 <- LE 7 in 1,879 of 1,879 carry links.
- Cross-LAB carry specimens (3 builds, 40-bit adder, `scripts/cycloneiv_clean_carry_specimens.py`): 6 links LE 15 of (x, y+1) -> LE 0 of (x, y), carry-in 120 / 0 / 0 / 0 incl. the 6 cross-LAB links; lut_site 123, lut_pin 240, lut_carry 120 all 100 %.

## Equivalence-sim findings (2026-10-30)
- Testbench artifact fixed: a port whose clkctrl net feeds only CLRN / data was driven by the shared clock (clear edge = clock edge); ffc_058 and ffc_118 pass since.
- Clock pad used as data (6 of the 14 remaining failures: rb_118, rb_058, sp_027, sp_087, sp_207, sp_267; 0 of 239 passing designs): in rb_118 the first diverging FF has equal q and D before the edge; the zero-delay GT dffeas samples D after the clock-derived data changed (D 1 -> 0 inside the edge time step), the emit samples before. With lcell outputs delayed 1 ps in GT (`--hold-safe`) the first FF agrees. Hold-safe mode reduces bad ports (rb_118 25 -> 11, sp_027 14 -> 3) but does not close all designs: not fully explained.
