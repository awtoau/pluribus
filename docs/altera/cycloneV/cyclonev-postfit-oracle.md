# Cyclone V post-fit oracle

Quartus's own post-fit netlist is the oracle for the Bluebird acceptance loop (Verilog -> Quartus -> bitstream -> decode + lift -> compare). The corpus pairs every hand-written source with Quartus's atoms, placement and routes, so it can also be mined for high-level lifting. Layout, tables, example SQL: `corpus/README.md`.

## What it checks

- Device `5CEBA4U19C8` (e50f), Quartus 25.1std.0 Lite (version string is recorded per build in `corpus_builds.toolchain`).
- Oracle inputs per build: `postfit.vo` (`quartus_eda --simulation --tool=modelsim --format=verilog`), `route_report.txt` (`quartus_sta`).
  - quartus_eda warns this is the "functional simulation netlist" (the only type for this device). It still carries every placed atom, all ports, defparams and `// Location:` comments.
- Lift under test: `mistral-cv decomp` -> `lifters/cyclonev_lift.py` -> `load.py` + `verilog.py` (`lifted.v`). The compare reads the lifter's own `Design.luts` / `Design.ffs`; it holds no LUT mapping.
- `scripts/cyclonev_postfit_compare.py`, per atom, at the same physical location:
  - `lut_mask` / `lut_mask_arith`: the lifted LUT table (wired through its LAB pins, over the nets) vs Quartus `lut_mask` on every reachable input vector, each port's `!` applied (`_arith` = ALM with `ARITH_SEL ADDER`). `lut.extra`: lifted LUT halves with no Quartus lcell.
  - `conn.<port>` / `conn_arith.<port>`: for every LUT data input, the atom driving it per Quartus vs the lifted LUT's own pin (or feedback register) via the DSU nets. A LUT the lifter did not emit, or a pin it does not wire, is LIFT_MISSING.
  - `conn.obuf.i`: driver of each output buffer, via the lifter's pad for that package pin, plus `!` (Quartus `.i(!...)` vs the lifter's pad inverter).
  - `ff.present`, `ff.extra` (lifted register with no Quartus register), `ff.d/clk/clrn/ena/sclr/sload`: driver + inversion of each control. `ff.d` = `asdata` when Quartus ties `sload` high. Quartus clock-enable buffers are traced through.
  - `ff.clk`: driver of the clock pin, traced through the lifter's clock-tree links (pad/PLL -> CMUX -> GCLK/RCLK -> SCLK, see "Clock tree"); an unresolved spine node stays LIFT_MISSING ("unbridged"). Also `ff.clk.edge` (polarity) and `ff.clk.domain` (lifted clock-root partition == Quartus clock-net partition, per design).
  - `pin`: package pin + direction vs the lifter's `Design.pads`.
  - `block.*`: DSP (`cyclonev_mac`), M10K (`cyclonev_ram_block`), clock control (`cyclonev_clkena`) -- no lifted model, always `QUARTUS_ONLY`.
- Verdicts: `MATCH`, `MISMATCH`, `LIFT_MISSING` (lifter has no value), `QUARTUS_ONLY` (no lifted counterpart at all), `LIFT_ONLY`, `UNMODELLED` (ALM mode the LUT mapping does not cover).
- Connectivity bridge (lifted source node -> Quartus atom), corpus-derived:
  - `LAB.x.y.alm:FF{T|B}{0|1|1L}` -> if `{T|B}DFF{0|1|1L}.alm = NLUT` the LUT of that half, else the register `FF_Xx_Yy_N(6*alm + 3*half + slot)`, half T=0/B=1, slot 1 = `FF?0`, slot 2 = `FF?1`/`FF?1L`.
  - `GPIO...:DATAIN` -> pin name from Mistral's comment -> Quartus `io_ibuf` on that pin.
  - `HMC...:IOINTDQDIN.n` -> same, pin name from the `.bt` line's comment (the lifter drops these).
  - A net's lifted driver = arc sources in its DSU set that are never an arc sink.

## Corpus

14 designs, all build OK end to end (2026-10-23, `python3.15t scripts/cyclonev_corpus_build.py`, ~16 s/design, rc 0):

| design | exercises |
|---|---|
| counter_en_aclr | counter, enable, async clear (from tmp/vo_demo) |
| regbank16 | 16x4 registers, shared enable, sync clear, read mux |
| adder12 | carry chain (ARITH_SEL ADDER) |
| comparator8 | combinational lt/eq/gt |
| fsm_seqdet | 5-state FSM, user encoding |
| shiftreg16 | shift register with enable |
| mult9x9, mult18x18 | DSP (`cyclonev_mac`; output regs absorbed into the DSP) |
| ram_inferred | inferred 256x8 M10K |
| ram_altsyncram | explicit `altsyncram` 512x16 M10K |
| dual_edge | posedge + negedge registers (Quartus: `clk` conn `inverted=1`; bt: `CLK2_INV`) |
| two_clocks | two clock domains + 2-FF synchroniser |
| clock_promotion | `GLOBAL CLOCK` -> `CLKCTRL_G8`, `REGIONAL CLOCK` -> `CLKCTRL_R54` |
| lut_random | 16 dense random 6-input functions (LUT mapping proof) |

- Timeouts (`OVERALL_S` in the build script): 3x the cold worst case measured on 2026-10-23 at loadavg ~4 (map 4.1 s, fit 7.5 s, asm 1.9 s, eda 0.7 s, cpf 0.4 s, sta 1.1 s, decomp 1.4 s, load/verilog 0.2-0.3 s); plus a 60 s no-output stall kill.
- A larger or RAM-heavy design will exceed these limits; raise the entry and record the new measurement here.

## LUT mapping: Quartus `lut_mask` <-> Mistral `LUT_MASK`

Not a single fixed permutation of 64 bits. It is a fixed per-half address function that depends on the ALM mode (`TMODE`/`BMODE`). Model (`lut_raw_pos()` in the compare script):

- Quartus lcell `LABCELL/MLABCELL_Xx_Yy_Nn`: ALM = `n // 6`, half = `(n // 3) % 2`: 0 = T (`TMODE`), 1 = B (`BMODE`).
- Raw bit = NOT Quartus output (the stored mask is inverted).
- B half: swap Quartus `datac`/`datad` before addressing.
- Address bit 5 (`x5`): Quartus `e` in modes `D_E`/`D_F`/`C_E`/`C_F` (defaults `D_E`/`C_E`), constant 0 in `E_0`, 1 in `E_1`.
- Address: `j = a | b<<1 | j2<<2 | j3<<3 | f<<4 | x5<<5`, with `(j2, j3) = (c, d)` if `x5 = 0` else `(d, c)`.
- MLAB: then `j -> MLAB_PERM[j]` (same table as nextpnr `mistral/lab.cc permute_mlab_init`).
- Only reachable input vectors count: Quartus inputs tied to `gnd` are 0 in the address. Bits outside that care set are don't-care.

How it was proven (`scripts/cyclonev_lut_pinmap_proof.py`, log `tmp/logs/cyclonev_lut_pinmap_proof.log`):

- 34 LABCELL lcells that alone fill an ALM with all 6 inputs used (16 random truth tables from `lut_random`, plus regbank/comparator muxes): solving per raw bit for a Quartus index consistent across all 34 gives a unique 64-to-64 bijection with output inversion. It equals the `D_E` address above.
- The full model on every lcell with a `LUT_MASK` (148: 135 logic, 13 arith; 55 use all 6 inputs): 147 MATCH, 0 MISMATCH, 1 UNMODELLED.
- Ablations: dropping any one feature breaks matches, so each one is supported by data:

| ablation | logic match / 135 | arith match / 13 |
|---|---|---|
| full model | 134 (+1 UNMODELLED) | 13 |
| no output inversion | 0 | 0 |
| T/B halves swapped | 63 | 7 |
| no B-half c/d swap | 124 | 11 |
| no hi-region c/d swap | 68 | 11 |
| no MLAB permutation | 109 | 13 |
| mode ignored (x5 = e always) | 116 | 9 |
| unused inputs not forced to 0 | 111 | 0 |

- Not proven:
  - `F_0`/`F_1` modes: one instance (counter_en_aclr `q[0]~0`, `BMODE F_1`); it fits no address function of its used pins. Reported `UNMODELLED`.
  - `D_F`/`C_F` vs `D_E`/`C_E`: no LUT difference seen in the data.
  - Arith ALMs match the same model, but `sumout`/carry semantics are not checked (only `combout` masks are compared).
- The mapping above is in Quartus port space. Every routed input port carries `!` (port = NOT net), so the lifted `init` is complemented on the routed letters (see "Polarity").

The mapping lives in the lifter (`_lut_table()`, `_port_pins()`); the compare only knows which LAB pin carries which Quartus port (`lab_pin()`).

Half mode = `<d source>_<e source>` (T: `D_E` default, `D_F`, `E_0`, `F_0`; B: `C_E` default, `C_F`, `E_1`, `F_1`):

| Quartus port | source |
|---|---|
| `a`, `b` | LAB pins `A`, `B` |
| `c` | T: `C`; B: `D` |
| `d` | first letter: `D` (T) / `C` (B) = that pin; `E` = `E0`/`E1`; `F` = same-half register feedback |
| `e` | second letter: `E` = `E0`/`E1`; `F` = same-half register feedback; `0`/`1` = constant (`x5`) |
| `f` | `F0` (T) / `F1` (B) |

- Feedback register = the `{T,B}_FEEDBACK_SEL` slot of the same half (0 -> `FF?0`, 1 -> `FF?1`): 262/262 corpus cells with an `F` letter: the driver of that port is a `dffeas` in the same ALM half, Quartus slot = FEEDBACK_SEL + 1. `F_0`/`F_1` therefore address like `E_0`/`E_1` with `d` taken from feedback; `D_F`/`C_F` differ from `D_E`/`C_E` only in `e`'s source (no LUT difference).
- Unrouted pins are folded (mask is don't-care there); no `LUT_MASK` line = stored all-ones = constant 0.
- Ablation table above was measured on the raw-mask model before this moved into the lifter.

## Lifter scorecard (2026-10-24, whole corpus, 235 designs scored of 236)

`scripts/cyclonev_lift_scorecard.py`: matched / (matched + missing + extra + wrong). m = LIFT_MISSING, x = extra (LIFT_ONLY), w = MISMATCH + UNMODELLED. Same compare for both columns; before = lifter at commit 22a87e13f (`--lifter-file`), after = this commit.

| field | before | before faults | after | after faults |
|---|---|---|---|---|
| lut function | 0/4234 (0.0%) | 4234 (m656 x1536 w2042) | 2463/2698 (91.3%) | 235 (m235 x0 w0) |
| lut inputs | 4704/8204 (57.3%) | 3500 (m3500 x0 w0) | 8204/8204 (100.0%) | 0 (m0 x0 w0) |
| ff.present | 1117/3276 (34.1%) | 2159 (m637 x1522 w0) | 1754/1754 (100.0%) | 0 (m0 x0 w0) |
| ff.d | 0/1754 (0.0%) | 1754 (m1754 x0 w0) | 1754/1754 (100.0%) | 0 (m0 x0 w0) |
| ff.clk | 0/1754 (0.0%) | 1754 (m1754 x0 w0) | 22/1754 (1.3%) | 1732 (m1732 x0 w0) |
| ff.clk.edge | 0/1754 (0.0%) | 1754 (m1754 x0 w0) | 1754/1754 (100.0%) | 0 (m0 x0 w0) |
| ff.clk.domain | 0/1754 (0.0%) | 1754 (m1754 x0 w0) | 1754/1754 (100.0%) | 0 (m0 x0 w0) |
| ff.clrn | 0/1754 (0.0%) | 1754 (m1754 x0 w0) | 1754/1754 (100.0%) | 0 (m0 x0 w0) |
| ff.ena | 0/1754 (0.0%) | 1754 (m1754 x0 w0) | 1754/1754 (100.0%) | 0 (m0 x0 w0) |
| ff.sclr | 0/1754 (0.0%) | 1754 (m1754 x0 w0) | 1754/1754 (100.0%) | 0 (m0 x0 w0) |
| ff.sload | 0/1754 (0.0%) | 1754 (m1754 x0 w0) | 1754/1754 (100.0%) | 0 (m0 x0 w0) |
| pins | 4341/4510 (96.3%) | 169 (m169 x0 w0) | 4341/4510 (96.3%) | 169 (m169 x0 w0) |
| obuf.i | 1493/1540 (96.9%) | 47 (m47 x0 w0) | 1493/1540 (96.9%) | 47 (m47 x0 w0) |

- 236 designs: 235 built OK; `c_ram_vnd_logic_16` failed `quartus_sta` (no oracle). Scored: 235 (a `decomp.bt` exists).
- `lut function` before counts the old lifter's output (inverted tables on mislabelled halves); the earlier "134 MATCH" was the raw `.bt` mask under the compare's own mapping, not the lifter.
- Remaining faults:
  - `lut function` 235 missing: one `~QUARTUS_CREATED_GND~I` per design (constant-0 lcell, no `LUT_MASK` line, output unrouted): no bitstream trace.
  - `ff.clk` 1732 missing: lifted source is a clock-tree spine node (`SCLK`/`HCLK` root), unnamed on the Quartus side. Needs the CMUX model (INPUT_SEL/CLKPIN_SEL -> pin). Same gap as the 13 dedicated clock pins in `pin`.
  - `pins` 169, `obuf.i` 47: pads reached through the HMC I/O path and dedicated clock pins (unchanged).
- Numbers are in-sample: the control rules below were read off this corpus and then scored on it.

## Register controls (corpus differential, all 1754 registers)

`_ff_controls()` in the lifter; every row is a crosstab of Quartus register features vs the bitstream, no exceptions unless stated.

| control | rule | evidence |
|---|---|---|
| register present | a non-nlut `FF{h}{0,1,1L}` port is routed, or the half's `F` mode feeds back from it | `ff.present` 1754/1754, 0 extra |
| D source | LUT-fed iff `{h}PKREG{1-slot}` is clear; pin-fed otherwise | 903 single-register ALMs (`d` from lcell vs `asdata`): 0 exceptions |
| pin-fed D pin | `{h}EF_SEL`: E -> T `E0`, B `E1`; F -> T `F1`, B `F0` | `ff.d` 1754/1754; the F pins are crossed vs the LUT halves |
| `sload` | constant 1 iff pin-fed, else 0 | Quartus `sload` const1 <=> `d` const0 + `asdata` pin; no `sload` signal in the corpus |
| clock select | `{T,B}CLK_SEL` names the pair {T0,B1} / {T1,B0}, not the half | single-register ALMs: T0->TCLK, T1->BCLK, B0->BCLK, B1->TCLK |
| clock source | `CLK<n>_INV`=1 -> clkb else clka (Mistral label swapped); clka `CLKIN.0` (`CLKA_SEL DIN0` -> `DATAIN.0`), clkb `CLKIN.1` (`CLKB_SEL DIN1` -> `DATAIN.1`) | fuzz item 6 + `ff.clk.domain` 1754/1754 |
| clock edge | `CLK<n>_SEL`=CLKB -> negedge | fuzz item 6; `ff.clk.edge` 1754/1754 (4 negedge regs, `dual_edge`) |
| MLAB clka | `CLKA_SEL GIN2` -> `DATAIN.0` | one design (`c_shiftreg_{sv,v95,vnd}_1`), 3 registers |
| enable | `EN<n>_EN`=0 -> constant 1; else clock n -> `DATAIN.2/3/0` (n=0/1/2) | 771 const + 983 signal, one candidate input each; polarity `EN<n>_NINV`=0 active-high (fuzz item 7; no inverted enable in the corpus) |
| async clear | `ACLR0_SEL`=ACLR0 -> constant 1; else `DATAIN.3`, `!` iff `ACLR0_INV`=1 | 1663 idle, 87 `sig!`, 4 `sig` |
| sync clear | half `SCLR_DIS`=1 -> constant 0; else `DATAIN.3` (`SCLR_SEL DIN1` -> `DATAIN.1`); unrouted input -> constant 0 | `SCLR_DIS` follows the half label (no crossing) |

- Not recovered (no evidence): `aclr1` (`{h}CLR_SEL`=1 never on a Quartus register), `CLK*_SEL`/`CLKB_SEL` values other than those above, inverted enable/sclr (`SCLR_INV`), `sload` as a signal, DSP/M10K registers.
- `ffs` has no polarity or clear columns: only plain posedge D flops get `d/clk/ce` in the DB (others stay undriven in `lifted.v`, as before). Full controls: `Design.ffs[i]["ctl"]`.

## Routing oracle (`route_report.txt`, `route_hops`)

- `quartus/route.tcl`: `derive_clocks -period 10` (every clock), virtual clock `vio` with zero input/output delay on all I/O, then `report_timing -setup` and `-recovery`, `-npaths 100000 -nworst 10 -detail full_path -show_routing`.
- Reachable: reg->reg in each domain, pad->reg, reg->pad, pad->pad (comparator8, lut_random), clock-tree hops (`clock path` section), async clear (`-recovery`: 4 paths in counter_en_aclr).
- Full per-net routing (all fan-out, clock network) from the RCF: `docs/altera/cycloneV/cyclonev-rcf-oracle.md`, table `rcf_routes`; 34% of nets are on no timing path.
- Not reachable via `route_hops`: nets on no timing path (constants, unused outputs). `-nworst 10` caps the paths reported per endpoint, so a high-fanout source is covered per endpoint, not for every pair.
- 1657 paths, 110,085 hops, 73,329 of them RE rows (5,601 distinct per build+location). No dedupe; `driver` (last cell output) names the net each hop routes.
- Quartus names map onto Mistral's: e.g. `R3_X1_Y19_N0_I1 (H_SEG3)` ~ Mistral `H3`, `C2_... (V_SEG2)` ~ `V2`. Not yet cross-checked against the `.bt` routes.

## Hand spot-checks (counter_en_aclr)

- LUT `q[2]~2`: `.vo` `LABCELL_X1_Y19_N42`, `lut_mask 64'h0000FFFF0505FAFA`, inputs a=en, c=q[0], e=q[2] (feedback), f=q[1].
  - DB: `postfit_atoms` x=1 y=19 n=42 -> ALM 7, half T. `.bt`: `LUT_MASK.7 03030302.00000001`, `TMODE.7 D_F`, `T_FEEDBACK_SEL.7 1`.
  - By hand: v=0 -> j=0, raw bit 0 = 1, inverted 0 = Q[0] (`...FA` bit 0 = 0). v=e only (16) -> x5=1 -> j=32, raw bit 32 = 0, inverted 1 = Q[16] = 1. Both agree.
  - Compare: `lut_mask MATCH`; conn a/c/f MATCH (`.bt`: `r LAB.001.019.0:FFB1L LAB.001.019.7:C` = q[0]); `datae` MISMATCH (feedback, no arc).
  - Lifted: two LUT5s `alm_lab_r1c19_a7_top`/`_bottom` with the raw (uninverted) halves. `_bottom` drives net `AA1`, which is input pin `F0`, not an output (see findings).
- Register `q[0]~reg0`: `.vo` `FF_X1_Y19_N5`, clk=`clk~inputCLKENA0_outclk`, d=`q[0]~0`, clrn=`rst_n`, ena=vcc, sclr/sload=gnd. DB conns hold exactly these (`const` 1/0 for vcc/gnd).
  - n=5 -> ALM 0, half B, slot 2 -> `FFB1`/`FFB1L`. Lifted `ff_lab_r1c19_a0_ffb1` (and a second register `..._ffb1l` for the same FF) -> `ff.present MATCH`. d/clk/... LIFT_MISSING (lifter leaves them None).
- Output `q[0]`: pin table `PIN_AA2` output, `q[0]~output` at `IOOBUF_X0_Y18_N79`, `.i` = `q[0]~reg0_q`.
  - `.bt`: `r TD.000.018.0040 GPIO.000.018.2:DATAOUT.0 ; AA2`. Lifter pad `AA2:out` -> `pin MATCH`. Its DSU net reaches `FFB1L` of ALM 0 -> `conn.obuf.i MATCH` (q[0]~reg0).
  - Route: `driver='q[0]~reg0|q'` hops include `LOCAL_LINE_X1_Y19_N0_I1`, `R3_X1_Y19_N0_I1`, `C2_X0_Y17_N0_I11`, `IO_OUTPUT_BUFFER_INPUT_X0_Y18_N79_I0`.

## Lifter findings (#106)

- Fixed: LUT polarity, halves, input order, bottom c/d swap, MLAB permutation; `F0`/`F1` are inputs; `NLUT` ports are LUT outputs, not registers; one register per physical register; registers independent of LUT halves; register feedback; absent `LUT_MASK` = constant 0.
- Not lifted (counted in `Design.unmodelled_halves`): MLAB `RAM`/`ROM` halves and undecoded `BMNONE`.
- (superseded, see "Arithmetic") `sumout`/carry was not modelled: arith halves were lifted as their `combout` LUT only.
- Old lifter: every non-zero 32-bit half incl. unused ones, every routed `FF*` port as a register (nlut pass-throughs, `FF?1`+`FF?1L` twice). Corpus check: lifted FFs 1754 = Quartus 1754.

## Verified vs assumed

- Verified on this corpus: the LUT model incl. `F_x` modes and feedback, T/B half and FF slot numbering, LAB pin per lcell port, register control rules above, the bridges.
- Assumed or unverified:
  - `D_F`/`C_F` vs `D_E`/`C_E` beyond the `e` source; arith `sumout`/carry.
  - `aclr1`, inverted enable / sclr, `sload` signal, MLAB `GIN3`.
  - Clock-tree source of a register clock (CMUX); DSP/M10K internals; Mistral routing-element names vs Mistral nodes.
- Single device/die and one Quartus version.

## Clock tree (2026-10-24)

Corpus now 236 designs (`c_ram_vnd_logic_16` has an oracle since its rebuild; its 1040 registers were the `ff.clk.domain` regression below). Same compare, 236 designs unless stated.

| field | before | after |
|---|---|---|
| ff.clk | 22/2794 (0.8%), faults 2772 (m2772 x0 w0) | 2794/2794 (100.0%), faults 0 |
| ff.clk.domain | 1754/2794 (62.8%), faults 1040 (m0 x0 w1040) | 2794/2794 (100.0%), faults 0 |
| pins | 4386/4556 (96.3%), faults 170 (m170 x0 w0) | 4493/4556 (98.6%), faults 63 (m63 x0 w0) |
| every other field | unchanged | unchanged |

- Split (sorted design list, even / odd index; same rules, nothing tuned per split): ff.clk even 2200/2200, odd 594/594; pins even 3352/3412 (m60), odd 1141/1144 (m3).
- Corpus clock sources are few: every design clocks from pad K17 (CMUXHG.054.022, inst 2 `INPUT_SEL` 6 = `NCLKPIN_SEL_2`; inst 0/1 in `clock_promotion`/`two_clocks`) or L17 (CMUXCR.054.002 inst 2). The split therefore checks the same CMUX paths twice; PLL inputs, other pins and `HR`/`VR` muxes have no corpus evidence.
- Chain (lifter `clock_tree_links()`, data `lifters/data/cyclonev_e50f_clocks.json` from `scripts/cyclonev_clock_tree_extract.py`, Mistral `e50f-r`/`e50f-cmux`/`cyclonev.cc`):
  - Quartus RCF element = Mistral node: `GLOBAL_CLOCK X0Y22 I10` = `GCLK.000.022.0010`, `SPINE_CLOCK X12Y0 I16` = `SCLK.012.000.0016` (counter_en_aclr, c_counter_sv_8: `X39Y0 I11`).
  - A default SCLK mux gets no `r` line (`cv-rmux.cc`: `dnode.t()==SCLK && default -> continue`). SCLK root source = the one candidate in its `e50f-r` source list whose CMUX instance has an `INPUT_SEL` setting (GCLK list index = instance; RCLK list index = instance for CR/HR/VR). 0 or >1 live candidates = no link, counted in `Design.clock_unresolved`.
  - CMUX instance input: `INPUT_SEL.<i>` (hex) indexes `cmux{hg,vg,cr,hr,vr}_link_table[i]` -> `CLKPIN_SEL_k` / `NCLKPIN_SEL_k` (label = slot in the CMUX `clkpin`/`nclkpin` list; default label 2k for G muxes, k for CR) or `PLLIN n` (`pllg`/`pllr`). Other kinds (`CLKIN`, `ICLK_SEL`, `SWITCH`) are not resolved.
  - Pad label: `s GPIO.x.y:<MUX>.<n> ... ; <pin>` names pad n of the tile (2428/2428 against the bi-qualified comments, 0 conflicts); the clock pads K17/L17 carry no `r` arc, only such comments.
  - Clock links are DSU unions, not `.bt` arcs: one clock reaching several sectors is one net (fixes the `c_ram_vnd_logic_16` 959 + 81 split).
- Scorecard option: `--split even|odd`.

## Self-feeding LUT latch

- `verilog.py` `_lut_self_latch()` REMOVED (64-char init = Cyclone V only). Self-feeding LUTs are plain combinational-loop `assign`s again.
- Evidence: corpus design `c_latch_v95_1` (SR latch, gated D latch, `q3 = ~(q3 & x)`), built with Quartus 25.1; structural compare all MATCH (lut_mask 5, conn 16, pins 8).
- `scripts/cyclonev_lifted_sim_check.py c_latch_v95_1 --zero x` (iverilog, lifted.v vs Quartus `build.vo`): Quartus netlist behaves as the source (q1 set/clear/hold, q2 follows `e`). Lifted: q1 never sets, q2 and q3 stay X.
- Why the function was wrong: it read (f0,f1) in port space, but every routed LUT port carries `!` in the netlist (port = NOT signal). Hold looks like (1,0) and was refused (q2); the oscillator `q3` looked like (0,1) and was emitted as a hold latch.
- The same script found the wider polarity gap; fixed, see "Polarity".

## Pads (2026-10-24)

| field | before | after |
|---|---|---|
| pins | 4493/4556 (98.6%), faults 63 (m63 x0 w0) | 4556/4556 (100.0%), faults 0 |
| obuf.i | 1509/1556 (97.0%), faults 47 (m47 x0 w0) | 1556/1556 (100.0%), faults 0 |

(Start of the session: pins 4386/4556, 170 missing; the 107 closed before this step were dedicated clock pads and pad comments, see "Clock tree".)

Classification of the 63 pins + 47 obuf.i still missing before this step:
- 60 pins + 47 obuf.i: pad reached through the HMC (top/bottom edge DDR I/O). Arc `r TD.. HMC.011.045:IOINTDQDOUT.20 ; D13` (fabric -> pin) or `r HMC.011.045:IOINTDQDIN.40 V2.. ; F15` (pin -> fabric); no GPIO arc. Lifter: `pc.hmc_pins` (node -> pin comment, `IOINT*DIN/DOUT` ports), `recover_pads()` makes the pad (DIN = in, DOUT = out, both = bidir), row/col/pio from the tile's GPIO annotation. Compare: `conn.obuf.i` uses the HMC DOUT node when there is no GPIO DATAOUT node.
- 3 pins (`up`, c_updown_{sv,v95,vnd}_1): unused input, only `USE_WEAK_PULLUP` settings, no arc. A configured pad with no arc -> `in`, no net (3/3 in the corpus are Quartus inputs, 0 outputs; an output always has a DATAOUT or HMC arc).
- Dedicated clock pins: closed with the clock tree (pad -> CMUX).
- Not evidence-backed: a pad that is both unrouted and an output (constant-driven output) would be mislabelled `in`; none in the corpus.

## Constant-0 LUT (`~QUARTUS_CREATED_GND~I`) decision (2026-10-24)

| field | before | after |
|---|---|---|
| lut function | 3288/3524 (93.3%), faults 236 (m236 x0 w0) | 3288/3288 (100.0%), faults 0, excluded 236 |

- Decision: oracle-side artifact, excluded from the score with verdict `EXCLUDED` (a row per cell, reason in `lifted_value`), counted in the scorecard `excl` column.
- Rule (generic, not name-based): a Quartus `cyclonev_lcell_comb` with no lifted counterpart, no input net on any data port and an output net that no atom reads.
- Evidence (236/236 designs, 236 cells): `lut_mask 64'h0`, all inputs `gnd`, `combout` net has 0 sinks in `postfit_conns`; the bitstream stores constants as unrouted pins (all-ones `LUT_MASK` = absent line), so the cell has no trace and no observable function.
- Not a lift fault: emitting a LUT with no sink would change no net. A cell that fits the rule but the lifter does emit is still scored.
- Scope: `combout` masks only; arithmetic `sumout`/`cout` are scored separately (see "Arithmetic"). Function of the emitted Verilog: "Functional sim gate".

## Arithmetic (2026-10-24)

| field | before | after |
|---|---|---|
| arith function (sum + cout + shareout) | 0/741 (0.0%), faults 741 (m741 x0 w0) | 741/741 (100.0%), faults 0 |
| arith cin/share (`conn.cin`, `conn.sharein`) | 0/431 (0.0%), faults 431 (m431 x0 w0) | 431/431 (100.0%), faults 0 |
| every other field | unchanged | unchanged |

Split (sorted designs, even / odd): arith function 661/661 / 80/80; cin/share 381/381 / 50/50.

- Oracle `arith.*` (compare): Quartus `sumout`/`cout`/`shareout` function from the `cyclonev_lcell_comb` simulation model (Quartus 25.1 `eda/sim_lib/cyclonev_atoms.v`, read as reference, not copied) evaluated on `lut_mask`, vs the lifted row over every vector of the connected inputs (`a b c d f cin sharein`); `conn.cin` / `conn.sharein` = driver atom of the pin vs the lifted source half. Rows exist only where the Quartus net is read.
  - `f0 = mask[15:0](a,b,c,d)`, `f2 = mask[47:32](a,b,c,dataf)`, `in2 = sharein` if `shared_arith` else `!f2`, `sum = cin^f0^in2`, `cout = maj(cin,f0,in2)`, `shareout = mask[47:32](a,b,c,d)`.
- Lifter (`_arith_luts()`): `ARITH_SEL ADDER` halves emit up to three rows on the 64-bit Mistral->Quartus table (`_lut_table` with no folding, since `f2` reads the `f=1` region):
  - `sum` (name = the plain half name, `z` = the NLUT/register net): letters a,b,c,d as before, e = cin, f = dataf (sharein in shared mode, where dataf is unused).
  - `cout` (`*_cout`) and `shareout` (`*_shout`) rows own new carry nets; emitted only while a later emitted half consumes them.
  - Chain: halves run T0,B0,T1,B1,... of a tile; cin = cout of the previous half (Quartus lcell N -> N+3: 314/314, sharein 84/84), cin = 0 at the start of an ADDER run. `SHARE=1` <=> `shared_arith on` (93/93; 254/254 off have no `SHARE`).
- Combout view kept for `lut_mask_arith`: rows carry `comb_init`/`comb_pins`.
- Not modelled: carry chain across a LAB boundary (cin of the first half of a tile is 0; no corpus chain crosses a LAB), two back-to-back chains in one ADDER run (not distinguishable in the bitstream), `extended_lut` (datag; `extended_lut off` in all 347 arithmetic cells).

## Polarity (2026-10-24)

Evidence: `scripts/cyclonev_polarity_evidence.py` (236 designs, `build.vo` + `decomp.bt`).

- LUT data inputs: every routed `cyclonev_lcell_comb` data port carries `!`: 11093 / 11093, 0 plain (includes LUT->LUT and register feedback). `cin` / `sharein`: never (314 + 84).
  - Quartus `lut_mask` indexes the complemented nets. Lifter: `init` bit v = mask bit (v XOR routed-letter mask) (`_complement_inputs`); arith rows complement a-d and `dataf`, not `cin` / `sharein`.
- Pad outputs: `.bt` inverter `i GPIO...:DATAOUT.n 1` (or `i HMC...:<..>DOUT.n 1`) <=> obuf `.i(!...)`: 38 / 38; no inverter <=> plain: 1518 / 1518; 0 exceptions.
  - Lifter: an explicit NOT row (`io_inv_<pin>`, `io_inverter`), the pad's `net_out` is its output; pad `out_inverted`.
- Complement experiment (pre-fix lifted.v, every lifted input driven complemented): `c_casemux_v95_4` 8036 / 8036 matched; `c_decoder_v95_3` 12054 / 16072, the 2 bad pins = the 2 inverted obufs.
- Compare (`cyclonev_postfit_compare.py`) now applies each port's `!`. Pre-fix lifter under it: lut function 253 / 3288 (wrong 3035), arith 356 / 741 (wrong 385), obuf.i 1518 / 1556 (wrong 38). After: 3288 / 3288, 741 / 741, 1556 / 1556. The old compare read 100% on the pre-fix lifter: it scored port-space masks and ignored the `!`.

## Functional sim gate (2026-10-24)

`scripts/cyclonev_lifted_sim_check.py --all`; blocking stage 5 of `scripts/cyclonev_verify_all.py` (any FAIL / ERROR fails the run). There is no "not covered" status: an atom without a model is a FAIL.

- Per design: re-lift `decomp.bt` with the current lifter, iverilog lifted.v vs `build.vo`, reset preamble then 2000 seeded random vectors, clocks in a separate phase. Inputs are defined at t=0 (an X-to-0 clock is not a negedge).
- Models under `build.vo`: our lcell / io / clkena models, Altera `dffeas`, the plain vendor RAM and MLAB models, our `cyclonev_mac`.
- Per output sample: matched | wrong | missing (lifted X or no port) | Quartus X (not scored). PASS = wrong 0, missing 0, matched > 0, model check not wrong.
- Model check: same `build.vo` + models vs `src/*.v`.
- Result table per kind: `docs/altera/cycloneV/cyclonev-status.md`.

| stage | pass | fail | not covered | matched / samples | wrong | missing |
|---|---|---|---|---|---|---|
| before (port-space masks) | 14 | 198 | 24 | 2114047 / 3804461 (55.6%) | 1677329 | 13085 |
| polarity fix | 160 | 52 | 24 | 3432695 / 3804461 (90.2%) | 362728 | 9038 |
| + emitter: pad-to-pad output, tie ignored LUT inputs | 165 | 47 | 24 | 3441733 / 3804461 (90.5%) | 362728 | 0 |
| + register controls (enable, aclr, sclr, negedge) | 212 | 0 | 24 | 3804461 / 3804461 | 0 | 0 |
| + RAM and MLAB (vendor models), 7 new designs | 241 | 0 | 2 | 4709178 / 4709178 | 0 | 0 |
| + DSP (own model), 9 new designs, 3 PLL designs | 252 | 3 (PLL) | 0 | 6125789 / 6125789 | 0 | 0 |

## Register controls (emitter)

- Lifter writes `ffs.d`, `clk`, `ce`, `lsr` (= sync clear) for every register; polarity flags and the async clear net ride in `ffs.dtype` (`cyclonev_alm_reg;clkinv=1;ceinv=1;lsrinv=1;clr=<net>;clrinv=1;miss=<fields>`). No schema change.
- `verilog.py` emit_ffs: `clrn` asynchronous clears, else on the clock edge `ena ? (sclr ? 0 : d) : hold` (Altera `PRIM_GDFF_LOW`: sclr is gated by ena). Negedge flops use `negedge`. A register with an unrecovered control (`miss=`) stays undriven and is listed.

## RAM and MLAB (2026-10-24)

Models: `cyclonev_ram_block` / `cyclonev_mlab_cell` in `cyclonev_atoms.v` are plain and wrap `generic_m10k` / `generic_28nm_lc_mlab_cell_impl` in `altera_lnsim.sv` (0 protect pragmas). The earlier "vendor models are encrypted" claim was wrong for RAM and MLAB; only the DSP, PLL and I/O-clock atoms are encrypted.

- iverilog -g2012 fails parsing the whole `altera_lnsim.sv` (line 32252). `scripts/cyclonev_lnsim_extract.py` copies the needed modules (12 of them, verbatim) into `tmp/simcheck/`; those parse and simulate. Verilator was not needed for RAM.
- Lifter: `lifters/cyclonev_hard.py` -> `Design.hard` -> table `cv_hard_cells` (JSON per atom) -> `verilog.py emit_hard_cells` instantiates the vendor atom with decoded parameters. Rules, each with 0 exceptions over the corpus RAM designs:
  - M10K widths: A = `A_DATA_WIDTH` (default 40), B = `B_DATA_WIDTH` (default 20). `ADDRB` routed: dual_port x40 (A writes, B reads); `ADDRA` only: single_port, or rom if no `WREN` / `DATAAIN`.
  - Address: pin = bit + `max(12 - max(abits, 8|9), 0)` (nextpnr `setup_m10ks`); abits = the smallest depth covering the routed pins. Data `DATAAIN.k` / `DATABIN.k` = `portadatain[k]` / `[20+k]`; `DATAAOUT.k` / `DATABOUT.k` = `portbdataout[k]` / `[20+k]` (single port: `portadataout`).
  - `WREN.0` or `WREN.1` (whichever is routed), `CLKIN.0|.6` = clk0, `CLKIN.1|.7` = clk1 (B side on clock1), `ENABLE.1` = ena0. `A_OUTPUT_SEL`/`B_OUTPUT_SEL` = REG: output clock0. `mixed_port_feed_through_mode` is "old" (not in the bitstream; simulation hint).
  - Contents: `RAM.<row>` = 40-bit row, inverted, bits permuted (nextpnr `write_m10k_cell`); a row holds 40/width words; row index bits above the design's address range read as 1 (rows 192..255 for 6 address bits). 4 init designs pass.
  - MLAB (one ALM half in RAM mode = one 32 x 1 cell): read address pins A,B,C,D,F0 of the ALM; data E0 (top) / E1 (bottom); write address F1 of ALMs 2,3,7,6,1; write clock / enable like a register's; contents `NOT raw[perm[(31 - v) + 32*bottom]]` (address inputs are inverted, like LUT inputs). 8 / 8 cells of `c_raminit_vnd_mlab_4` matched by an exhaustive search over bit permutations and complements (unique solution: complement all five).
- Corpus: `c_raminit_vnd_{m10k_4,m10k_16,mlab_4}`, `c_rom_vnd_{m10k_8,mlab_8}`, `c_ramsp_vnd_m10k_8`, `c_ramdc_vnd_m10k_8` (`scripts/cyclonev_construct_gen.py`). Quartus placed `c_rom_vnd_mlab_8` in an M10K.

## DSP (2026-10-24)

Method: (a) reference = the design's own source RTL, simulated directly; (b) our own `cyclonev_mac` model (`lifters/data/cyclonev_mac_model.v`) from the Cyclone V handbook (vol. 1 ch. 3, `sources/cyclonev-device-handbook.pdf`) and the atom's parameters, validated before use: `build.vo` on our model vs source RTL on all 11 corpus DSP designs (`scripts/cyclonev_dsp_model_check.py`, 0 wrong). The lifted side then runs on the same model and is also compared to the source RTL (model-independent).

- Modelled: `m9x9` (lane 0), `m18x18_full`, `m27x27`, `m18x18_sumof2`; per-operand input registers; output register. Everything else gives X.
- Mistral MODE: `M9X9`, absent = `m18x18_full` (18x19), `M27X27`, `M18X19_COMBINED` = `m18x18_sumof2`.
- Pin -> port bit (pad correlation, `DATAIN.n` of bank bi, `RESULT.k` = `resulta[k]`):
  - m9x9: ax = bank0, bx = bank1, ay = bank2, by = bank3 (lane 0 evidenced).
  - m18x18_full: ax = banks 0,1; ay = banks 2,3; `ay[18]` = bank5.8.
  - m27x27: ax = banks 0,6,7; ay = banks 2,8,9.
  - sumof2: as m18 plus bx = banks 6,7; by = banks 8,9; `by[18]` = bank11.8.
- Signedness and registers (Mistral lane names are swapped against the atom's in the single-lane modes): `signed_max/may` = `BX/BY_SIGNED`, `ax/ay_clock` = `INREG_CTRL_BX/BY`, `output_clock` = `OREG_CTRL`; in sumof2 the names follow the atom.
- Vendor cross-check (2026-10-26, Questa-Altera Starter 2025.2, `scripts/cyclonev_dsp_vendor_check.py`): our model vs the encrypted `cyclonev_mac`, side by side, random operands / enables / clocks.
  - Configs: the 11 corpus instances (exact defparams) + seeded random configs over the 4 modelled modes (signedness, operand and output clocks random, result width 64).
  - Found: `m9x9` bits above 17 were wrong (model sign-extended the product). Vendor: all-ones iff both operands are signed and negative, else 0. Fixed; `m9x9` with operands > 9 bits now gives X.
  - After the fix, seed 2, 256 random + 11 corpus configs x 1000 steps: 267 / 267 configs, 51264000 / 51264000 bits agree; wrong 0, missing 0.
- Corpus: `mult9x9`, `mult18x18` plus `c_dsp_*` (signed / unsigned 9, 18, 27; input regs, output reg, combinational; sum of two products).

## PLL (2026-10-26)

- Vendor atoms (`cyclonev_fractional_pll`, `cyclonev_pll_output_counter`, `..._refclk_select`, `..._reconfig`) are encrypted; Questa-Altera Starter runs them (precompiled `cyclonev_ver`). iverilog cannot.
- Corpus: `c_pll_vnd_m2d1_1`, `c_pll_vnd_m4d1_2`, `c_pll_vnd_m3d2_1` (50 MHz in, 75 / 100 / 100 + 200 MHz out).
- Decode (`lifters/cyclonev_hard.py fpll_cell`): f = ref * M / N / C, M = `M_CNT_HI+LO`, N = `N_CNT_HI+LO`, C = `DPRIO0_CNT_HI.c + LO.c` of counters with `Cc_COUT_EN`; unset hi / lo are 1. 4 / 4 output counters match the Quartus defparams.
- Netlist (lifter):
  - refclk pad: `CLKIN_0_SRC` = 4 + position of the pad in the FPLL's `clkin` list (Mistral `data/e50f-fpll.txt`). 13 / 13 pin-site combinations built with the refclk pinned (`c_pllpin_*` plus the H10 `c_pll_vnd_*`); PLL site forced with `set_location_assignment FRACTIONALPLL_X<x>_Y<y>_N0 -to p|general[0].gpll~FRACTIONAL_PLL`:

| FPLL tile | value 4 | 5 | 6 | 7 |
|---|---|---|---|---|
| 054.037 | H10 | G13 | - | - |
| 000.037 | K7 | G10 | H10 | G13 |
| 054.000 | U13 | T15 | L17 | - |
| 000.000 | P9 | R10 | U13 | T15 |

  - Table: `lifters/cyclonev_hard.py` `FPLL_REFCLK_PAD`; the 12 new designs all PASS the Questa gate (decode 1/1 each).
  - `CLKIN_0_SRC` = 0: refclk from a fabric register or another PLL's output (both measured), i.e. the clock network; detected, NOT LIFTED (reason in the lifted comment).
  - A refclk on a pin without a PLL route is a fitter error (177020), no bitstream. `PL_AUX_BG_POWERDOWN` appears on the left-top tile; treated as analog.
  - reset: routed net into `FPLL:NRESET0`; `NREVERT_INVERT` = 1 <-> Quartus `nreset_invert = "true"` (active-high).
  - lock: `FPLL:LOCK0` routed net.
  - output counter c -> `FPLL:CLKOUT.c` -> CMUX `PLLIN` -> GCLK -> SCLK (clock-tree table): C3 = 100 MHz LAB domain, C5 = 200 MHz MLAB domain in `m4d1_2`, confirmed by the sim gate.
  - Settings outside the modelled set (phase / presets, bypass, fractional, other `CNT_IN_SRC`, `VCO_DIV`) -> NOT LIFTED with the key.
- Behaviour of the vendor sim model (measured in Questa, `tmp/qexp` probes; now `lifters/data/cyclonev_fpll_model.v`):
  - `locked` = 1 at the first refclk posedge with reset inactive; 0 at once on reset.
  - VCO first rising edge at lock, re-aligned to refclk every N / gcd(M, N) refclk cycles; stops while unlocked.
  - Output counter: high for HI VCO cycles, low for LO; odd-duty correction falls on the VCO negedge half a cycle early. State is kept across reset; the first VCO edge after power-up is not counted.
- Gate: the 3 designs PASS on Questa (vendor atoms vs our model). Mutation check: counting the first VCO edge fails all 3 (5960-21197 wrong samples).
