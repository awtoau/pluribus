# Cyclone V post-fit oracle

Quartus's own post-fit netlist is the oracle for the Bluebird acceptance loop (Verilog -> Quartus -> bitstream -> decode + lift -> compare). The corpus pairs every hand-written source with Quartus's atoms, placement and routes, so it can also be mined for high-level lifting. Layout, tables, example SQL: `corpus/README.md`.

## What it checks

- Device `5CEBA4U19C8` (e50f), Quartus 25.1std.0 Lite (version string is recorded per build in `postfit_builds.toolchain`).
- Oracle inputs per build: `postfit.vo` (`quartus_eda --simulation --tool=modelsim --format=verilog`), `route_report.txt` (`quartus_sta`).
  - quartus_eda warns this is the "functional simulation netlist" (the only type for this device). It still carries every placed atom, all ports, defparams and `// Location:` comments.
- Lift under test: `mistral-cv decomp` -> `lifters/cyclonev_lift.py` -> `load.py` + `verilog.py` (`lifted.v`). The compare reads the lifter's own `Design.luts` / `Design.ffs`; it holds no LUT mapping.
- `scripts/cyclonev_postfit_compare.py`, per atom, at the same physical location:
  - `lut_mask` / `lut_mask_arith`: the lifted LUT table (wired through its LAB pins) vs Quartus `lut_mask` on every reachable input vector (`_arith` = ALM with `ARITH_SEL ADDER`). `lut.extra`: lifted LUT halves with no Quartus lcell.
  - `conn.<port>` / `conn_arith.<port>`: for every LUT data input, the atom driving it per Quartus vs the lifted LUT's own pin (or feedback register) via the DSU nets. A LUT the lifter did not emit, or a pin it does not wire, is LIFT_MISSING.
  - `conn.obuf.i`: driver of each output buffer, via the lifter's pad for that package pin.
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
- The Quartus `!` on a LUT input is not a polarity of the mask. Every routed input carries `!`. An input fed back from the ALM's own register also carries `!`, but the mask then reads the uninverted value (two_clocks `ca[0]~3`: equation `!ca[0]`, mask `FFFF0000FFFF0000` over `e`). The model is in Quartus-mask space and needs no per-pin inversion.

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
- Full per-net routing (all fan-out, clock network) from the RCF: `docs/cyclonev-rcf-oracle.md`, table `rcf_routes`; 34% of nets are on no timing path.
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
- DJI ground sample (`cyclonev_verify_all.py`): 33336/11502/144296 -> 6511/7855/15818 LUTs/FFs/nets. Old: every non-zero 32-bit half incl. unused ones, every routed `FF*` port as a register (nlut pass-throughs, `FF?1`+`FF?1L` twice). Corpus check: lifted FFs 1754 = Quartus 1754.

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

## Ground-side loops (DJI ground FPGA, label `G`, no oracle)

`python3.15t scripts/run_pipeline.py --board <awto-dji>/ground/fpga --label G --workers 8` (PLURIBUS_SQLITE_PATH under `tmp/`). `check_verilog.py` combinational loops: 4 before this step.

| LUT | mode | function (f0,f1 = output with own net at 0 / 1) | class |
|---|---|---|---|
| `alm_lab_r10c7_a8_bottom` | E_1 | `z = z \| ~s` | set-hold latch |
| `alm_lab_r10c18_a7_bottom` | E_1 | `z = z \| s` | set-hold latch |
| `alm_lab_r16c2_a9_bottom` | E_1, `ARITH_SEL ADDER` | `z = ~(s & z)` | arithmetic ALM: `FFB0` is the adder `sumout`, lifted as the LUT `combout` |
| `alm_mlab_r9c6_a5_bottom` | F_1 | 16 assignments hold/set, 8 invert | unresolved |

- Self-feeding LUT = own output routed to its own input pin (`FFB1L -> A/B`, same ALM). Not a pin/half mix-up: all four are `FFB?` outputs of a bottom half going back to a pin that half uses.
- Fix (`verilog.py` `_lut_self_latch()`, 64-char init only): per assignment of the other inputs, (f0,f1) = (1,1) set, (0,0) clear, (0,1) hold -> `always @*` latch (yosys `$dlatch`, passes the gate as a state element). (1,0) for any assignment = can oscillate = not a latch: left as a loop.
- After this step: 2 loops (rows 3 and 4, both with oscillating assignments); row 3 closed by "Arithmetic", row 4 see "Ground-side verify, final".

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
- Scope of "lut function 100%": `combout` masks only. Arithmetic `sumout`/`cout` are not scored (see "Arithmetic").

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

## Ground-side verify, final (2026-10-24)

`G` (DJI ground FPGA, no oracle): LUT rows / FFs / nets 6511 / 7855 / 15818 (#106) -> 6691 / 7855 / 15926 (5588 plain + 798 sum + 243 cout + 62 shareout rows). `check_verilog.py`: no-driver 587 -> 522, combinational loops 4 -> 1.

| loop | root cause | fix |
|---|---|---|
| `alm_lab_r10c7_a8_bottom`, `alm_lab_r10c18_a7_bottom` | set-hold latch built as a LUT with output -> own input (genuine feedback) | `_lut_self_latch()` in `verilog.py` |
| `alm_lab_r16c2_a9_bottom` | lifter fault: ADDER ALM lifted as `combout`; `sumout` has no such dependence | `_arith_luts()` (Arithmetic) |
| `alm_mlab_r9c6_a5_bottom` | open: `F_1` bottom half whose `F1` pin carries its own output, 8 of 32 assignments invert; the ALM's `ARITH_SEL` raw is 4 and `TMODE.5` raw is 1 (both outside Mistral's tables) | none |

- The remaining loop is the only blocker of the gate (yosys: one `$shiftx` self loop, 0 errors, 0 conflicting drivers).
- Mode fields outside Mistral's tables, G only (0 in the 236-design corpus): `ARITH_SEL` 15322 lines `BMNONE`; `TMODE`/`BMODE` 16010 halves `BMNONE` (mistral-cv drops the raw value; read with a patched copy of `cv-bmux.cc`, 2026-10-24). Raw `TMODE`/`BMODE` values are spread over 1,2,8 (~1070 each in LABs), 3,5,6,c (~360-470), a,b,d,e,f; `ARITH_SEL` raw 0 (8623), 4 (2378), 2 (2107), 5, 3, 7 against 6 (`lut`, default) in 3%. The distribution is the same for idle ALMs and ALMs with routed inputs and outputs, and only 125 ALMs have >= 3 routed inputs plus a routed output. Reading: the G image uses other values than the 25.1 flow for unused or alternative ALM modes; those halves are not lifted (`Design.unmodelled_halves`). Not verifiable without a Quartus oracle for that flow.
- Clock links in G: 32 SCLK roots resolved, 42 not (32 ambiguous, 10 without a configured source): every CMUX instance in G carries a non-default `INPUT_SEL` (same effect as above), so "configured instance" does not single out the live one. Unresolved = missing, never guessed.
