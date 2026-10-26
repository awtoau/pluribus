# ECP5 Diamond routing oracle (#109)

Diamond 3.14 placed-and-routed `.ncd` files read with `ncdread` + `ncd2nmc -r -io`; `scripts/ecp5_oracle_compare.py` scores the pluribus decode + lift (`lifters/ecp5_lift.py`) against them. Twin of `docs/machxo2-diamond-oracle.md`.
Numbers: full run 2026-10-24, Diamond 3.14.0.75.2 NCDs built 2026-07-29/30, lifter and `device-db/` as of the commit adding this file. Findings only: lifter, `native_trellis/`, `device-db/` untouched.

## Tools (no licence needed)

- `ncdread <ncd>` and `ncd2nmc -r -io <keep.txt> -o out.nmc <ncd>` run on ECP5 `.ncd` with no licence check (run while the licence was expired): 219 targets, 438 tool logs, no licence message, rc 0. No synthesis / PAR was run. `trce`, `ldbanno` not exercised.
- `-io` is required on ECP5 too. `dm_counter` without it: 10 pad comps + their sigpins deleted, nmc holds 13 of 23 comps. `keep.txt` = comps whose site is an iodb package pin (`N3`, `B10`); slices are `R<r>C<c><A-D>`, EBR `EBR_R<r>C<c>`, SED `SED`.
- Tool wall time (12 workers): ncdread max 1.7 s, ncd2nmc max 6.6 s (85F). `TOOL_TIMEOUT_S` = 20 s.

## Inputs

- Routed `.ncd` + `.bit` pairs (read in place from the main checkout, gitignored):
  - `corpus/diamond/<dev>_dm_*/impl1/dm_*_impl1.ncd`: 15 builds (5 designs x 25F/45F/85F). `*_map.ncd` (mapped, unrouted) is not used.
  - `diamond-fuzz/targets/sedga_*/impl1/fuzz_impl1.ncd`: 284 targets; 204 routed + `.bit`; 80 have no routed NCD (failed builds; reported as `no_ncd`).
- 219 targets (12F x 51, 25F x 56, 45F x 56, 85F x 56). The ~657 `.ncd` estimate does not hold: 438 `.ncd` exist, half are `*_map.ncd`.
- The 228 third-party bitstreams in `corpus/ecp5/` have no NCD: no oracle, only the global-drop census below.
- Content: 1808 PIO, 519 SLICE, 200 SED, 3 EBR comps; 2717 nets (all routed), 21,657 route arcs, 228 clock nets (`PAR_CLOCKSIGNAL`).
- **No PLL, DCC/DCS comp, SERDES or DSP in any target.** Clock trees are pad -> implicit DCC -> spine -> branch only; PLL / `G_DCS*` clocking is not exercised by the oracle (see census).

## `.nmc` format: same as MachXO2

- `parse_nmc()` parses all 219 files to EOF with no change; arch string `sa5p00`. Same magics, sections, property types, source -> sink arcs (driver at the tree root, leaf-first order).
- Only values differ:
  - placement grid 20 slots per row (MachXO2 14)
  - pad sites are BGA balls, not pin numbers
  - control pin wires `CLK{0-3}_SLICE`, `LSR{0-3}_SLICE`, `CE{0-3}_SLICE`; carry `FCI_SLICE`, `FCOA_SLICE`..; slice data pins use the same `{A,B,C,D,M,F,Q,DI}{2*slice+bit}_SLICE`
  - the reference comp may be a pad on another row than any slice
- Validation (all 219): 2530/2530 ncdread comps in the nmc, 0 config differences, 6578/6578 pin -> net pairs, 2717/2717 nets routed, 21,657 arcs, 228/228 clock nets routed, 0 `ncd2nmc` deletions.

## Coordinates

- Wire `R<dr>C<dc>_<wire>` is relative to the reference comp's tile; anchor = `site - (dr, dc)` by slice-pin majority vote.
  - ECP5 high-fanout nets repeat a pin wire name in many tiles (`A0_SLICE` in every slice), so a name match is ambiguous: `build_oracle(unique_votes=True)` votes only when the name occurs once among the net's pins and once among its wires. Without it 3 of the first 20 targets failed ("no majority anchor"). MachXO2 keeps `False`; 20 MachXO2 targets re-run, `oracle.json` identical.
- Placement trailer: `y = (max_row - row) * 20 + slot`, `x = col`; `max_row` from `devices.json` (25F 50). 2327 slices + pads checked against ncdread: 0 row/column/slot mismatches.
- **Diamond row = graph row, Diamond column = graph column** (`col_bias` 0; MachXO2 is 1). Evidence: every slice site (e.g. `R38C70A`) holds a PLC2 tile in the decode; right pads at x = 72 = `PICR0` column; top pad `B10` at x = 29 = `PIOT0` R0C29.
- Pad column vs iodb: 0 on all edges (MachXO2 +1/+1/0/+2). Slot: top/bottom = PIO letter; left/right reversed (A=3 .. D=0).
- Anchor = placement anchor in 19 targets; in 200 (SED designs) the reference comp is the SED block and its routing tile is one row off its placement tile; slice-pin votes unanimous.
- Warnings: 208 `route_multi_driver`, 200 `anchor_relplace_differs`.

## Batch

`python3.15t scripts/ecp5_diamond_oracle.py [--workers 12]`: 69.9 s, 219 ok, 0 failed, 80 `no_ncd`. Resumable (`oracle.json` newer than NCD + `schema_version`); output `corpus/ecp5/diamond-oracle/<target>/` (gitignored via `corpus/ecp5/`).

## Comparison

`python3.15t scripts/ecp5_oracle_compare.py [--workers N] [--force] [--report]` (RAM gate = `heavy_guard.wait_available`; 85F one at a time; resumable by `schema_version`). 219/219 compared, 0 failed; ~15 min with 85F sequential.

Verdicts: MATCH; MISMATCH (both have it, differ: sink driven by another pip, net split or merged); LIFT_MISSING (Diamond has it, lift does not); ORACLE_ONLY (Diamond has it, outside what pluribus models or names); LIFT_ONLY (decoded arc on no Diamond route). Every non-MATCH is a fault.

### Normalisation of Diamond names (counts = wire lookups)

- Row/col: identity. `X_SLICE`/`X_PIO` -> `X` for DSU lookup: 2706. `DI#` -> `F#` (lifter reads D from the LUT F, `ff_d_source`): 306. `CLK#`/`LSR#_SLICE` -> `MUXCLK#`/`MUXLSR#` when the config drives the mux (lifter `_prefer_mux_nodes`): 488.
- `G_` prefix added when the bare name is absent in the tile: 261 (HPBX, VPTX).
- Edge span segment alias (same rule as MachXO2, e.g. `H06W..02` -> hop alias on `..03`): ~1000 lookups.
- Unresolved at their Diamond tile (counted `wire_not_in_graph`): global tree wires `HPRX` 230, `JPCLKT` 228, `VPFS` 225, `CLKI/CLKO_TDCC` 225 each, `TDCC#CLKI` 225, `VPTX` 209, `LLPCLK` 162, `LRPCLK` 45, `ULPCLK` 22, `HPFE`/`LDCC` 3, `JSEDCLKOUT_SED` 200, edge spans `H#E#` 467, `H#W#` 95, `V#N#` 131, `V#S#` 25.
- Global-tree arcs (either end `G_`/`R_`/`L_` or unlocated) are matched to decoded arcs by name pair, not location: prjtrellis names them at tiles (TMID, CMUX, EBR_SPINE, TAP_DRIVE) other than the one Diamond uses. 928 pips matched this way (`global_name_pair_only`); a location-exact match is not possible. This is the weakest evidence in the table.
- Several tiles share a position (PLC2 + TAP_DRIVE): the slice tile check uses all of them.

### Headline (every non-MATCH counted as a fault)

| category | matched / total | rate | faults | by verdict |
|---|---|---|---|---|
| pips | 11,581 / 26,677 | 43.4% | 15,096 | MISMATCH 141, LIFT_MISSING 231, ORACLE_ONLY 9,704, LIFT_ONLY 5,020 |
| nets | 1,400 / 2,717 | 51.5% | 1,317 | MISMATCH 1,128 (split or merged), LIFT_MISSING 189 |
| connections (driver -> load pin) | 1,004 / 4,069 | 24.7% | 3,065 | LIFT_MISSING 2,653, MISMATCH (split) 222, ORACLE_ONLY 190 |
| register clocks | 0 / 429 | 0.0% | 429 | MISMATCH 429 (clock net not connected to its driver) |
| sites (fields) | 5,712 / 5,805 | 98.4% | 93 | ORACLE_ONLY 93 (FF ce/lsr whose Diamond net is split in the lift: 21 + 72) |

- Sites not scored: 144 LUT INIT fields of DPRAM/RAMW slices (RAM contents, not compared), 260 SRMODE fields on registers with no LSR net (no mux arc to read).
- Site fields all MATCH: LUT INIT 1151, MODE 515, GSR/CEMUX/CLKMUX 326 each, LSRMUX/SRMODE 66 each, REGSET/SD (decoded and lifted) 421 each, lifted GSR 421.
- Pips that are not clock-related are also faulty; see causes below.

### Pip causes

| verdict:cause | count | detail |
|---|---|---|
| MATCH | 11,581 | 5,901 decoded; 2,556+54 fixed conns joined in the lift; 928 global pairs by name; 289 decoded global-name; 351 no-bits mux joined; 153 `F->DI` |
| MISMATCH sink_driven_by_other_pip | 141 | all `F#_SLICE -> F#`: decode says `F# <- F5#_SLICE` / `FX#_SLICE` |
| LIFT_MISSING pip_nobits_not_unioned | 231 | `JPADDIA_PIO -> JDIA` (106), `JPADDIB_PIO -> JDIB` (119), `JPADDI -> JINCK` (6): pad input mux default, no bits |
| ORACLE_ONLY fixed_outside_lift_dsu | 3,487 | pad output `JA# -> JPADDO*`, `JPADDO* -> PADDO*_PIO` (no pad node in the lift DSU), carry `FCO -> HFIE -> FCI` |
| ORACLE_ONLY arc_not_in_graph | 3,439 | die-edge span turnarounds (`H#W# -> W#_H#W#`, `W#_H#W# -> W#_H#E#`), pad `JPADDI -> JINCK` 222, `JPADDIA_PIO -> JPADDI` 219 |
| ORACLE_ONLY one_wire_not_in_graph | 1,864 | edge spans 1,300+, `JINCK -> JPCLKT#` 228, `JSEDCLKOUT_SED -> JF#` 200 |
| ORACLE_ONLY wire_not_in_graph | 914 | DCC / PCLK / HPRX global wires with no name at the Diamond tile |
| LIFT_ONLY fabric | 4,144 | left/right-edge turnaround arcs with hop names (`W#_H#E# -> W#_H#W#` 511, ...), default `SYNCECLK# -> JECLK#` 4 x 438, `F5#/FX#_SLICE -> F#` |
| LIFT_ONLY global_name | 876 | `G_DCS#CLK# <- G_VPFN#`: 4 per design, present in all 219 decodes, whatever the design clocks |

## Global clock analysis

Register clock = driver pad -> CLK pin of each register (429 registers on 225 clock nets; 3 EBR clock pins and 24 WCK pins are connections, not registers). Verdict MATCH needs the lift to put the driver and the CLK pin in one DSU class. Result: 0 / 429.

- Lift gives every register a non-constant clock net (0 constants): the clock resolves to a per-tile island, not to the Diamond net. 225 Diamond clock nets became 250 lift clock nets (210 intact as one island, 8 x 2, 4 x 3, 3 x 4 islands; the single-island ones are single-tile designs whose driver is still unconnected).
- `dm_counter` 25F end to end (`clk` pad B10 -> 24 registers in tiles C67..C70 of R38): Diamond is one net; the lift has 4 nets (`n49` C67, `n51` C68, `n53` C69, `n55` C70) with no driver.
  - kept in the lift: `R38C70 CLK1 <- G_HPBX0000` key (70,38,G_HPBX0000), same in C67/C69; `TAP_DRIVE R38C60 R_HPBX0000 <- G_VPTX0000` key (60,38,..); `EBR_SPINE_LR1 R37C59 G_VPTX0000 <- G_HPRX0000` key (59,37,..): each key carries the referencing tile, so the keys never meet.
  - dropped (`gkey()` None): `TMID_0 R0C31 G_TDCC2CLKI <- G_JPCLKT00`, `CMUX_LR_0 G_VPFS/G_LRPCLK`, `CMUX_* G_DCS#CLK# <- G_VPFN#`.

### Clock path, per family (registers broken = registers whose path contains the failing arc)

| family (src>sink) | registers through | lift fate |
|---|---|---|
| `JPADDIA_PIO>JPADDI`, `JPADDI>JINCK`, `JINCK>JPCLKT#` | 429 | not decoded (pad -> clock-pin mux has no config arc / no graph pip) |
| `JPCLKT#>TDCC#CLKI` (and `LDCC`) | 429 | decoded, **dropped**: `G_JPCLKT#`, `G_TDCC#CLKI` parked at (0,0) (TMID_0 / LMID_0) |
| `TDCC#CLKI>CLKI_TDCC#`, `CLKI_TDCC#>CLKO_TDCC#`, `CLKO_TDCC#>VPFS#` | 429 | not decoded, wires unnamed at the Diamond tile (the DCC itself) |
| `VPFS#>LLPCLK#` | 231 | decoded, **dropped** (`G_VPFS#`, `G_LLPCLK#`; CMUX_LL_0) |
| `VPFS#>LRPCLK#` | 154 | decoded, **dropped** (CMUX_LR_0) |
| `VPFS#>ULPCLK#` | 36 | decoded, **dropped** (CMUX_UL_0) |
| `LLPCLK#/LRPCLK#/ULPCLK#>HPRX#` | 231 / 154 / 36 | not decoded (quadrant -> row root has no config arc) |
| `HPRX#>VPTX#` (EBR_SPINE_*) | 429 | decoded and kept per tile |
| `VPTX#>HPBX#` (TAP_DRIVE, `R_HPBX#`) | 429 | decoded and kept per tile |
| `HPBX#>CLK#` / `LSR#` (PLC2) | 429 | decoded and kept per tile |
| join `HPRX#>VPTX#` / `VPTX#>HPBX#` | 429 | **unlinked**: per-tile keys differ |
| join `VPTX#>HPBX#` / `HPBX#>CLK#` | 429 | **unlinked** |
| `CLK#>MUXCLK#`, `MUXCLK#>CLK#_SLICE` | 429 | ok |

- Quadrant cases seen: lower-left (`LLPCLK`) 231 registers, lower-right 154, upper-left 36, upper-right 1 (EBR clock). Spine (`HPRX`/`VPTX`/`HPBX`) is positional in the lift but unlinked across tiles. `G_DCS*` is only ever decoded as a default arc; no target exercises a DCS or PLL clock.
- Every register fails on at least 7 distinct arcs/joins of its path; fixing the (0,0) parking alone would not recover it (the not-decoded arcs and the positional joins remain).

### Clock-tree shapes in Diamond (driver -> leaf, families; count = clock nets)

| nets | shape |
|---|---|
| 160 | `JPADDIA_PIO < JPADDI < JINCK < JPCLKT# < TDCC#CLKI < CLKI_TDCC# < CLKO_TDCC# < VPFS# < LLPCLK# < HPRX# < VPTX# < HPBX# < CLK# < MUXCLK#` |
| 40 | same, `LRPCLK#` quadrant |
| 20 | same, `ULPCLK#` quadrant |
| 3 | `JPADDIC_PIO < ... < LDCC#CLKI < CLKI_LDCC# < CLKO_LDCC# < HPFE# < LRPCLK# < HPRX# < VPTX# < HPBX# < LSR# < MUXLSR#` (reset on a left DCC) |
| 2 | `... < VPFS# < ULPCLK# < HPRX# < VPTX# < HPBX# < JCLK# < JCLKA_EBR` (EBR clock) |
| 2 | `... < HPBX# < CLK# < WCK#_SLICE` (distributed-RAM write clock) |
| 1 | `... < URPCLK# < HPRX# < VPTX# < HPBX# < JCLK# < JCLKA_EBR` |

### Chip-global names the lift parks at (0,0) and drops (decoded arcs, 219 Diamond bitstreams)

| name family | endpoints dropped | tile types |
|---|---|---|
| `G_DCS#CLK#`, `G_VPFN#` | 876 each | CMUX_LL/LR/UL/UR_0 (219 each) |
| `G_JPCLKT#` | 228 | TMID_0 225, LMID_0 3 |
| `G_VPFS#` | 227 | CMUX_LL 162, LR 42, UL 22, UR 1 |
| `G_TDCC#CLKI` | 225 | TMID_0 |
| `G_LLPCLK#` / `G_LRPCLK#` / `G_ULPCLK#` | 162 / 45 / 22 | CMUX_LL / LR / UL |
| `G_HPFE#`, `G_LDCC#CLKI`, `G_URPCLK#` | 3, 3, 1 | CMUX_LR, LMID_0, CMUX_UR |

Off-grid hop names also dropped (edge turnarounds, not globals): `W#_H#E#` 453, `S#_V#N#` 131, `W#_H#W#` 90, `S#_V#S#` 25, `E#_H#E#` 14, `E#_H#W#` 5.

### Third-party census (decode only, no oracle): families the lift drops

12 of 228 third-party bitstreams (evenly spaced sample; the full run did not finish: RAM gate starved by other jobs, 40- and 60-design attempts abandoned). 15,726 global-named arc endpoints, 15,307 kept (positional `HPBX`/`VPTX`/`HPRX`, `L_`/`R_HPBX`), 419 dropped. Per-tile positional keys are kept but unlinked (as in the Diamond table), so "kept" is not "connected".

| dropped family | endpoints | designs (of 12) | tile types |
|---|---|---|---|
| `G_DCS#CLK#`, `G_VPFN#` | 48 each | 12 | CMUX_UL/UR/LL/LR_0 |
| `G_HPFE#` | 61 | 9 | CMUX_* |
| `G_VPFS#` | 44 | 6 | CMUX_* |
| `G_LLPCLK#` / `G_LRPCLK#` / `G_ULPCLK#` / `G_URPCLK#` | 32 / 32 / 31 / 31 | 10-11 | CMUX_LL / LR / UL / UR |
| `G_LDCC#CLKI` / `G_TDCC#CLKI` / `G_RDCC#CLKI` | 20 / 11 / 4 | 9 / 6 / 2 | LMID_0 / TMID_0 / RMID_0 |
| PLL outputs `G_JLLCPLL#CLKOP/OS`, `G_JULCPLL#CLKOP/OS`, `G_JLRCPLL#CLKOP/OS` | 6+5+3, 4+5+1, 2+2 | 2-6 each | LMID_0, TMID_0, RMID_0, ECLK_L |
| `G_J{LL,UL}CPCLKCIB#`, `G_JTRQPCLKCIB#`, `G_JLLQPCLKCIB#`, `G_{LL,UL}CPCLKCIB#` (fabric -> clock) | 7+4+3+1 | 1-3 | CMUX_*, TMID_0, LMID_0 |
| `G_JPCLKT#` | 4 | 3 | LMID_0 |
| `G_HPFW#` | 10 | 2 | CMUX_* |

- Unlike the Diamond targets, these exercise PLL (`CLKOP/CLKOS`), DCS (`G_DCS#CLK#`), fabric-driven clocks (`CPCLKCIB`/`QPCLKCIB`) and all four DCC sides. None of that has Diamond routing as oracle: the claim here is only that the lift drops the named endpoints.

## Other findings

- **`F# <- F5#_SLICE` / `FX#_SLICE` decoded arcs are probably bit aliasing, not wide muxes.** `bits.db` PLC2: `.mux F0` option `F5A_SLICE` = `F8B10`, and `SLICEA.CCU2.INJECT1_0` `NO` = `F8B10` (`YES` = `!F8B10`); same for `FXA_SLICE`/`F8B11`/`INJECT1_1`. In `dm_counter` (all slices CCU2) every slice decodes `F0 <- F5A_SLICE`, `F1 <- FXA_SLICE` while Diamond routes `F0_SLICE -> F0` (141 pip MISMATCH, plus LIFT_ONLY). Verified for `dm_counter`; that all 141 sit on CCU2 slices was not checked. If confirmed, the "wide muxes in 204/211 designs" corpus figure counts this alias (`docs/ecp5-corpus.md`).
- The default arcs `G_DCS#CLK# <- G_VPFN#` (4 per design) and `*_SYNCECLK# -> *_JECLK#` (8 per design) are decoded in all 219 designs (LIFT_ONLY); unclear whether they are real default routes or the same kind of alias.
- Pad routing (`JA# -> JPADDO*`, `JPADDI* -> JINCK`) has no lift node: 3,487 + ~450 pips and 190 connections are ORACLE_ONLY / LIFT_MISSING.
- Carry chain `FCO -> HFIE -> FCI`: `FCI_SLICE` loads are LIFT_MISSING connections (known gap, now counted).
- Die-edge turnaround arcs: same family as MachXO2 `RoutingGraph.cpp:166/:293`; Diamond names them one way, decode the other; both sides are faults (ORACLE_ONLY and LIFT_ONLY).

## Spot checks (raw -> oracle.json -> lift)

1. `dm_counter` net `led_c_7` (SLICE_0 Q0 -> SLICE_0 B0 + pad `led[7]`, site `R38C70A`, pad N3): ncdread pins `Q0`, `B0`, `PADDO`. nmc (ref `rst`, anchor R26C0): `R12C70_Q0 -> R12C71_H02E0001 -> R13C71_V02S0001 -> R14C71_V00B0000 -> R14C71_JA3 -> R12C72_JPADDOD`; oracle.json absolute R38/R39/R40. Lift: R38C70 `E1_H02E0001 <- Q0`, R38C71 `S1_V02S0001 <- H02E0001`, R40C71 `V00B0000 <- N1_V02S0001`, `JA3 <- V00B0000`: all MATCH; `JA3 -> JPADDOD` (pad) ORACLE_ONLY.
2. `dm_counter` net `n102` (F0 -> DI0, `R38C70`): `F0_SLICE -> F0 -> DI0 -> DI0_SLICE` fixed / modelled by `ff_d_source`; lift `ff_r38c70_A0.d = n47`; MATCH.
3. `dm_counter` net `clk_c`: ncdread `clk` PADDI at B10 + 13 slice CLK pins; nmc `R-26C29_JPADDIA_PIO -> ... -> R-25C31_CLKO_TDCC2 -> R-13C31_VPFS0200 -> R5C31_LRPCLK0 -> R11C45_HPRX0000 -> R12C59_VPTX0000 -> R12C65_HPBX0000 -> R12C67_CLK1 -> MUXCLK0 -> CLK0_SLICE`; absolute R0C29 ... R38C65 HPBX ... R38C67 CLK1. Lift: see the end-to-end list above; 24 registers on 4 nets; register-clock MATCH 0 / 24.

## Verified vs assumed

- Verified: licence-free `ncdread` / `ncd2nmc` on ECP5 NCDs; nmc grammar (219 files to EOF); comp / pin-net / net / clock-net completeness; Diamond row/col = graph row/col; 20-slot placement formula; anchor method; every count above; MachXO2 parser unchanged (20 targets identical).
- Assumed: global-tree pips matched by name pair (location not verifiable); the F5/FX alias explanation beyond `dm_counter`; meaning of `unk_*` header fields (as MachXO2); that `PAR_CLOCKSIGNAL` marks primary clock nets.
- Not covered: PLL, DCS, SERDES, DSP clocking (no Diamond target uses them; census sample only, no oracle), the other 216 third-party bitstreams in the census, other ECP5 variants (UM/5G), timing.

## Gate (#123)

- `python3.15t scripts/ecp5_gate.py [--workers 2]`: builds missing Diamond designs (3 dies x 12 designs), oracle, compare, one table; baseline `tests/baselines/ecp5_oracle.json` (per target + total, date/commit/conditions inside).
- Exit 1 if any target's missing/extra/wrong in any category rises, or a baseline target is absent; exit 2 on a build/oracle/compare error. New targets are listed until `--update-baseline`.
- Headline = matched / (matched + missing + extra + wrong). Verdict map: LIFT_MISSING + ORACLE_ONLY = missing, LIFT_ONLY = extra, MISMATCH = wrong.
- compare.json is cached on a code stamp (lifters, native_trellis, device-db/ECP5, compare script), so a lifter edit recomputes.
- Baseline 2026-10-26 (merged main incl. #116, 219 targets): pips 12,876 / 26,521 (48.6%); nets 1,441 / 2,717 (53.0%); connections 1,373 / 4,069 (33.7%); register clocks 429 / 429; sites 5,784 / 5,805.
- `ecp5_verify_all.py` (nextpnr reference, closed loop) is a change detector only, not in the gate.
- Added designs: `dm_mux32`, `dm_mux64` (OFX wide muxes), `dm_add_cmp` (CCU2), `dm_ebr_dp` (DP16KD, two clocks), `dm_distram` (DPRAM/RAMW), `dm_dsp` (MULT18X18D), `dm_gsr` (GSR:ENABLED, #118).
- #118: `dm_gsr` uses `FD1S3AX` with `GSR="ENABLED"`; Diamond writes `GSR:ENABLED`, the bitstream omits it (DB default). Old lifter: 8/8 lifted FF gsr MISMATCH; with the DB default: 8/8 MATCH. LSE-inferred registers are always `GSR:DISABLED`, so no earlier target exercised it.

## Rerun

```
python3.15t scripts/ecp5_diamond_oracle.py                 # ~70 s
python3.15t scripts/ecp5_oracle_compare.py [--workers N]    # ~15 min, 85F sequential
python3.15t scripts/ecp5_global_drop_census.py --thirdparty-only [--sample N] [--workers 1]   # decode-only; RAM-bound
```

Logs: `tmp/logs/ecp5_diamond_oracle.log`, `ecp5_oracle_compare.log`, `ecp5_global_drop_census.log`. Summaries: `corpus/ecp5/diamond-oracle/_batch_summary.json`, `_compare_summary.json`, `global_drop_census.json`.
