# aw2 board lift status (label V07, LCMXO2-1200)

- Command: `PLURIBUS_SQLITE_PATH=<scratch>.db python3.15t scripts/run_pipeline.py --board boards/aw2-2d82auto --label V07 --workers 8`
- Field-by-field diff for regression: `scripts/lift_summary.py --label V07 --out X.json` then `--diff X.json`.
- Scoring rule: missing connection = fault (CLAUDE.md "Scoring faults"). Counts below are raw.

## Baseline (main 0bb7c5378, 2026-10-24)

| | V07 | V02 |
|---|---|---|
| LUTs (pseudo-LUT count, device has 1280) | 2636 | 2611 |
| FFs | 1093 | 1112 |
| nets | 4304 | 4262 |
| EFB ports in / out | 21 / 9 | 23 / 10 |
| EFB config | SPI sel 0x54 | 2 blocks |
| yosys gate | PASS | PASS |
| no-driver wires (gate) | 270 | 231 |
| DB-level undriven nets (no LUT/FF/EFB/pad driver) | 528 | 490 |
| conflicting drivers / comb loops / reg loops / other warn | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| sim_no_ip.py | COMPILE FAILS (`efb_inst.wb_poke` unscoped, instance is `dut.efb_inst`) | not run |

## Round-trip depth (#84)

- `scripts/machxo2_roundtrip.py` (known-source scope RTL, not the board bitstream): bounded miter PROVEN to cycle 52, DIVERGES at 53 (first serialised readback bit).
- cs_n high: PROVEN 80 cycles. DPRAM forced 0: still diverges (readback datapath gap).
- Board bitstream has no source: no LEC possible. Structural round-trip = lifted Verilog -> Diamond -> decode -> compare (not yet run on the board design).

## Step 2: EFB config + inputs (#100)

- Inputs were already lifted (21 in / 9 out, unchanged). New: oracle comparison of the input side (docs/efb-config.md): 20/(20+0+1+0) pins match Diamond; the 1 fault is WBCLKI (global spine, #109).
- Board-design inputs with no driver in the lift: JWBCLKI (alias of the spine clock input, driven by testbench), JSPISCSN (on `G_HSBX0201`, #109).
- EFB instance now carries decoded attributes (`EFB #(.EFB_SPI("ENABLED"), .SPI_MODE("SLAVE"), ...)`); config bits outside the oracle table print UNEXPLAINED (none in V07/V02).
- Lifter regression: V07 and V02 summaries differ only in `v_bytes`/`v_sha256` (EFB parameter block).

## Step 3: hard-IP models + simulation (#49)

- Command: `python3.15t scripts/sim_no_ip.py --board boards/aw2-2d82auto --label V07 --config tmp/v7/FPGA_V07.bin.config [--run-us 60] [--tie-undriven 0|1]`
- Hard IP in the bitstream: 1 EHXPLLJ (tile PT1), 1 EFB (SPI), 7 EBR. No OSC. DCC arcs are pass-through in the lift.
- PLL: dividers decoded from the config (`pll_decode.py`), word = DIV-1, verified with Diamond builds (`scripts/pll_oracle.py`: I_DIV 3, FB_DIV 7, OP_DIV 5 match; OS/OS2/OS3 from the existing `ehxpllj_4out` target). Board: I=1, FB=10, OP/OS/OS2/OS3 = 2/4/8/2, INT_DIVD feedback.
  - The only Fin that makes the output set cover the annotated spine rates {62.5, 125, 250} MHz is 50 MHz (unique): CLKOP 250, CLKOS 125, CLKOS2 62.5, CLKOS3 250.
  - Output -> spine track is the board annotation (`board.toml [sim.pll_tracks]`), not recovered: global-wire routing is #109.
- EFB model: `scripts/efb_open_model.v`, WISHBONE + SPI registers 0x54..0x5D, hardened SPI front end driven by the testbench. Register semantics are TN1205-modelled, not recovered or vendor-checked.
- Testbench: PLL model drives the three primary clocks (before: all 125 MHz), SPI frames from `spi_registers.tsv` on the EFB, FPGA_nCS idle high (before: constant 0).
- Fixed on the way: boot sequence called `efb_inst.wb_poke` unscoped (compile error); blackbox-strip regex did not match the parameterised stub.

Results (60 us run-out after the SPI script, 1093 FFs, 270 undriven wires):

| mode | FFs X at end | FFs seen 0 and 1 | WB reads | WB writes | SPI bytes |
|---|---|---|---|---|---|
| as recovered | 247 | 70 | 0 | 0 | 48 |
| undriven wires forced 0 (what-if) | 2 | 97 | 6862 (all a=0x01) | 0 | 48 |
| undriven wires forced 1 (what-if) | 1 | 217 | 0 | 0 | 48 |

- As recovered the design does not run: the WISHBONE master state machine depends on undriven nets, so STB/CYC never rise.
- The what-if rows are exploration only (tie-offs are invented), but show the undriven wires are the sole X source in the datapath.
- Undriven wires (yosys check, 270): 201 raw `n<id>` nets, 44 `ghost_d_*`, 8 output-pad nets (pin4, pin61, U7_DS, U1_STCP, DAC_CLK, ADC_ENCA, ADC_ENCB, ADC_ENCB_n1570), 17 other named (carry/EBR/LUT-derived).
- No SPI-register traffic (a=0x5A/0x5B) appears in either what-if: the fabric never consumes the SPI bytes in this lift. Whether that is a lift gap or the real design reads them through paths in the undriven set is open.

## Step 4: structural round-trip (#84, #38)

- Command: `python3.15t scripts/aw2_roundtrip.py --board boards/aw2-2d82auto --label V07 --config tmp/v7/FPGA_V07.bin.config [--ghosts-as-inputs]`
- Flow: `out/V07.v` (EFB stub dropped so Diamond uses the primitive; vendor EFB port names now emitted) -> Diamond LSE + map + PAR + bitgen -> native decode -> `diamond_roundtrip.compare_configs` against the original decode. Pads located from `pad_map`; bank VCCIO is board data (banks holding an SSTL25 pad are 2.5 V, so LVTTL-class pads there are emitted LVCMOS25, else PAR rejects the bank).
- Diamond runs measured 5-8 s (this design collapses; see below).

Stages reached (2026-10-24):

| stage | result |
|---|---|
| lift -> Verilog, yosys gate | pass |
| Diamond LSE | accepts; 307 warnings: 72 registers stuck at zero, 158 undriven nets patched with GND |
| map | 1 register, 3 LUT4, 2 slices; 0 of 7 EBR, 0 of 1 PLL |
| PAR, bitgen, native decode | pass (after the bank fix above) |
| compare vs original | 2 of 1257 LUT INITs matched, 1255 missing, 0 extra; tiles 56 vs 271; enum residual 4418, arc residual 12817, config-line residual 3218 |

Headline (LUT INIT multiset, canonical under input permutation): matched / (matched + missing + extra + wrong) = 2 / (2 + 1255 + 0 + 0) = 0.16%. Registers configured: 1 vs 1070 in the original decode.

- Blocking construct: every output pad is constant after synthesis. Two causes, both missing connections:
  1. 270 undriven wires, patched to GND by LSE (158 reach logic).
  2. 59 of 1093 FFs recovered with constant D = 1'b0 and shown as "stuck-at-reset": 40 of them select the M input (`REGn.SD 0`) and the config routes that M wire; 19 select the LUT. This includes the registers behind 12 pad outputs. The lifter's fallback turns an unresolved D into 0.
- `--ghosts-as-inputs` (experiment: the 263 undriven internal wires become input ports, synthesis + map only): still 3 registers / 4 LUT4, because cause 2 keeps the outputs constant.
- Not in the lift at all: the PLL (0 of 1 used; clocks are input ports), so LSE sees the primary clocks as plain pads (#104).
- Known-source round-trip (`machxo2_roundtrip.py`): proven to cycle 52, diverges at 53 (unchanged since baseline).

## #113: constant-D flip-flops, undriven nets (2026-10-24, label V07)

Before = main 5f2d4bdcd + loud-fault commit. After = branch wt-113.

| | before | after |
|---|---|---|
| FFs with constant D | 64 (59 x 1'b0, 5 x 1'b1) | 5 (1'b1, absent paired LUT) |
| FFs with D fault flagged (`ffs.d_fault`) | 43 (const-0 RESET) | 1 (DPRAM write pin unconnected) |
| gate no-driver wires / DB undriven nets | 270 / 528 | 271 / 529 |
| V02 constant-D FFs / no-driver wires | 54 / 231 | 5 / 233 |
| oracle: pips matched / total | 80,532 / 134,261 | 80,532 / 134,261 |
| oracle: nets matched / total | 18,325 / 19,498 | 18,325 / 19,498 |
| oracle: register-clock nets | 1,876 / 2,996 | 1,876 / 2,996 |
| oracle: register D nets (new headline) | n/a | 2,972 / 2,996 (16 M-unconnected, 8 DPRAM write unconnected) |
| Diamond rebuild LUT INIT: matched / missing / extra / wrong | 2 / 1255 / 0 / 0 (0.16%) | 4 / 1253 / 0 / 0 (0.32%) |
| rebuild REGSET enums (orig 1070) | 1 | 5 |

- Root cause of the 59: `const_by_root` treated an all-0 INIT as a constant LUT in DPRAM/RAMW slices; there the INIT word is RAM contents and F is the read port. Every FF and LUT input reading a DPRAM F resolved to 1'b0.
  - 41 FFs read F directly; 18 read M-routed nets whose root was a DPRAM F. 6 of the 41 also needed F rooted before the DPRAM pass names it.
  - Not wire canonicalisation, not missing arcs, not the 44,100 ORACLE_ONLY fixed conns.
- `scripts/undriven_classify.py` on the 287 undriven-and-read nets: 185 global-spine arc dropped (#109), 46 edge H06 hop-3 stub arc dropped by `gkey()`, 45 edge H06 wire with no driver (turnaround), 10 other (5 EBR1-tile `JF`, 2 EBR1-tile `JQ`, 1 bottom-edge pad `JQ`, 1 clock pin, 1 DPRAM read with unconnected write pin).
- Edge H06 stubs: the Diamond corpus holds one H06 turnaround (`H06W0301 -> H06E0304` at col 1, 4 arcs) and no hop-3 stub arc; no rule beyond the existing col-hops == -1 one is derivable from it. Needs a Diamond build routing hop-3 H06 near the die edge.
- The rebuild still collapses: output pads stay constant while the clock tree, edge stubs and EBR read outputs are open.

## 2026-10-26 re-measure (label V07, branch of main c20155649 + guard rollout)

Rebuild = `aw2_roundtrip.py` (Diamond LSE + map + PAR + bitgen, compare to the original decode).

| | session start | now |
|---|---|---|
| gate no-driver wires / DB undriven nets | 270 / 364 | 36 / 118 |
| nets / FFs | 4,139 / 1,101 | 3,955 / 1,105 |
| rebuild LUT INIT: matched / missing / extra / wrong | 4 / 1,253 / 0 / 0 (0.32%) | 229 / 1,028 / 44 / 0 (17.60%) |
| rebuild registers (original 1,070) | 5 | 205 |
| rebuild LUT4 (original 1,257) | 4 | 273 |
| LSE warnings | 309 | 96 |

- Undriven-and-read nets at start (258): 158 global-spine (1,101 FF.CLK + 144 FF.LSR + 126 FF.CE pins), 55 edge H06 turnaround, 33 edge H06 stub, 12 other. Now 25: 10 clock nets (PLL/DCC roots, hard IP not emitted, 1,105 FF.CLK pins), 15 other (EBR read outputs `JF`/`JQ`, slice `F0`/`HF0W` fast connects).
- Fixed from oracle evidence (docs/lattice/machxo2/machxo2-diamond-oracle.md): H-span fold at the die edge (88 nets), secondary network CE/LSR/fabric tracks (148 nets), CENTER clock mux joint decode, cross-tile CCU2 carry (`n_luts` 2,637 -> 2,689: 52 more CCU2 half-slices now emit sum/carry logic), FF GSR default.
- Remaining collapse of the rebuild (LSE keeps 205 of 1,070 registers): logic that only reaches hard IP is pruned. Not emitted: 7 EBR (0 of 7 mapped), PLL (0 of 1), IOLOGIC DDR inputs (15 ADC pads "no load"), output DDR (ADC_ENC, DAC_CLK "no driver"); the EFB is emitted.
- Counts in the first table are change detectors; `n_luts` above 1,280 still measures lifter faults.
