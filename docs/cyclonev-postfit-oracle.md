# Cyclone V post-fit oracle

Quartus's own post-fit netlist is the oracle for the Bluebird acceptance loop (Verilog -> Quartus -> bitstream -> decode + lift -> compare). The corpus pairs every hand-written source with Quartus's atoms, placement and routes, so it can also be mined for high-level lifting. Layout, tables, example SQL: `corpus/README.md`.

## What it checks

- Device `5CEBA4U19C8` (e50f), Quartus 25.1std.0 Lite (version string is recorded per build in `postfit_builds.toolchain`).
- Oracle inputs per build: `postfit.vo` (`quartus_eda --simulation --tool=modelsim --format=verilog`), `route_report.txt` (`quartus_sta`).
  - quartus_eda warns this is the "functional simulation netlist" (the only type for this device). It still carries every placed atom, all ports, defparams and `// Location:` comments.
- Lift under test: `mistral-cv decomp` -> `lifters/cyclonev_lift.py` (unchanged) -> `load.py` + `verilog.py` (`lifted.v`).
- `scripts/cyclonev_postfit_compare.py`, per atom, at the same physical location:
  - `lut_mask` / `lut_mask_arith`: Quartus `lut_mask` vs Mistral `LUT_MASK.<alm>` under the mapping below (`_arith` = ALM with `ARITH_SEL ADDER`).
  - `conn.<port>` / `conn_arith.<port>`: for every LUT data input, the atom driving it per Quartus vs per our DSU nets (lifted source node bridged back to a Quartus atom by location).
  - `conn.obuf.i`: driver of each output buffer, via the lifter's pad for that package pin.
  - `ff.present`, `ff.d/clk/clrn/ena/sclr/sload`: register present at that place; driver of each control.
  - `pin`: package pin + direction vs the lifter's `Design.pads`.
  - `block.*`: DSP (`cyclonev_mac`), M10K (`cyclonev_ram_block`), clock control (`cyclonev_clkena`) — no lifted model, always `QUARTUS_ONLY`.
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

LAB input pins per lcell port (from connectivity: `conn.*` MATCH counts):

- `a`->`A`, `b`->`B`; T: `c`->`C`, `d`->`D`; B: `c`->`D`, `d`->`C`; `e`->`E0`/`E1`, `f`->`F0`/`F1` (T/B).
- In `E_0`/`E_1` the half's `d` comes in on `E0`/`E1` (comparator8 `Equal0~1/~2` resolve only this way).

## Current verdict counts (whole corpus, 2026-10-23)

| field | MATCH | MISMATCH | LIFT_MISSING | other |
|---|---|---|---|---|
| lut_mask | 134 | 0 | 14 | 1 UNMODELLED |
| lut_mask_arith | 13 | 0 | 0 | |
| conn.dataa/b/c/d/f | 67/70/73/66/128 | 0/0/0/1/0 | 0 | |
| conn.datae | 49 | 26 | 1 | |
| conn_arith.* | 24 | 0 | 0 | |
| conn.obuf.i | 151 | 0 | 13 | |
| ff.present | 80 | 0 | 52 | |
| ff.d/clk/clrn/ena/sclr/sload | 0 | 0 | 132 each | |
| pin | 321 | 0 | 38 | |
| block.* | | | | 18 QUARTUS_ONLY |

- `lut_mask LIFT_MISSING` 14 = one `~QUARTUS_CREATED_GND~I` per design: all-zero mask, no `LUT_MASK` line in the bitstream.
- `conn.datae` MISMATCH: 24 are LUT inputs fed from the ALM's own register (`{T,B}_FEEDBACK_SEL=1`, annotated in `lifted_value`). 2 more (two_clocks `cb[0]~3`, `cb[3]~2`) are register feedback with no arc and no annotation. `conn.datad` 1 is the same feedback case (`F_1`).
- `conn.obuf.i` LIFT_MISSING: 12 adder12 + 1 lut_random outputs on HMC-path pins (no lifter pad).
- `pin` LIFT_MISSING 38: 24 adder12 + 1 lut_random HMC-path pins; 13 dedicated clock inputs (`K17`, `L17`) that reach the fabric through clock muxes, not a `GPIO` arc.

## Routing oracle (`route_report.txt`, `route_hops`)

- `quartus/route.tcl`: `derive_clocks -period 10` (every clock), virtual clock `vio` with zero input/output delay on all I/O, then `report_timing -setup` and `-recovery`, `-npaths 100000 -nworst 10 -detail full_path -show_routing`.
- Reachable: reg->reg in each domain, pad->reg, reg->pad, pad->pad (comparator8, lut_random), clock-tree hops (`clock path` section), async clear (`-recovery`: 4 paths in counter_en_aclr).
- Not reachable: nets on no timing path (constants, unused outputs). `-nworst 10` caps the paths reported per endpoint, so a high-fanout source is covered per endpoint, not for every pair.
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

## Lifter findings (`lifters/cyclonev_lift.py` not changed here)

- LUT polarity: the raw `LUT_MASK` is the inverted function. The lifter emits raw bits as `init`, so every lifted LUT is complemented.
- LUT halves: the lifter splits lo32 = "bottom" (FFB*), hi32 = "top" (FFT*), inputs A,B,C,D,E0/E1.
  - Measured: in E_x mode lo32 belongs to the T half (TMODE). The address is a,b,c,d,f with e as region select (L6) or constant (E_x), B sees C/D swapped, MLAB bits are permuted.
  - The lifted LUT functions are therefore wrong for every mode. Only the raw bits are right.
- `F0`/`F1` are LUT inputs, not combinational outputs. The lifter uses them as LUT `z`, which collides with routed nets (counter_en_aclr: `alm_lab_r1c19_a7_bottom` drives `AA1`).
- Combinational outputs leave through `FF*` ports when `{T,B}DFF*=NLUT`. The lifter emits every routed `FF*` port as a register: comparator8 12 and lut_random 16 lifted FFs with 0 Quartus registers, equal to their NLUT setting counts.
- `FF?1` and `FF?1L` are two outputs of one register; the lifter emits two registers.
  - Corpus totals: lifted 153 FFs vs 132 Quartus `dffeas`; lifted 212 LUT5 vs 162 lcells.
- `ff.present LIFT_MISSING` 52: 46 because FF emission is gated on the lifter's (mislabelled) LUT half being non-zero, or the ALM has no LUT_MASK. 6 are registers whose Q leaves by no arc (feedback only).
- FF d/clk/ena/clr/sclr/sload: all 132 LIFT_MISSING (known gap).
- Register feedback (`{T,B}_FEEDBACK_SEL`) is not modelled: 24-27 LUT-input mismatches.
- Pads: no pad for dedicated clock pins or HMC-path pins (38 of 359 Quartus pins).

## Verified vs assumed

- Verified on this corpus: the LUT model (ablations above), T/B half and FF slot numbering, LAB pin per lcell port, the bridges, every MATCH count above.
- Assumed or unverified:
  - `F_0`/`F_1` LUT addressing.
  - What `D_F`/`C_F` change.
  - Arith `sumout`/carry.
  - `TCLK_SEL`/`BCLK_SEL` vs FF half (in counter_en_aclr, `TCLK_SEL.0` sits on an ALM whose register is half B; not investigated).
  - DSP/M10K internals.
  - Mapping of Quartus routing-element names to Mistral nodes.
- Single device/die and one Quartus version.
