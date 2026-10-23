# MachXO2 Diamond routing oracle (#105)

Diamond 3.14 exports the placed + routed design of every MachXO2 fuzz target; `scripts/machxo2_oracle_compare.py` checks the pluribus decode + lift against it.
Numbers below: full corpus run, 2026-10-23, Diamond 3.14.0.75.2, worktree at the commit that adds this file.

## Tools

- `ncdread <ncd>`: per comp, its site (`R9C11A`; pads by package pin), full config string, pin -> net.
- `ncd2nmc -r -io <keep.txt> -o out.nmc <ncd>`: binary hard macro holding every routed net, arc by arc.
  - `-io` is required. Without it ncd2nmc deletes every I/O comp and **unroutes any net a pad drives** (log: `This sigpin is driver. The whole signal is unrouted.`). `keep.txt` = one comp name per line (all comps whose ncdread site is a pin number).
  - `-p` changes nothing (placement is always kept). `-noglobal`: no difference on `clkdivc_div2` or `dcca` (DCC comp and full clock tree kept either way).
- `ncdread` also reads `.nmc`: prints the comp list, reference comp and `relplaceinfo` (used to confirm the placement trailer below).
- `arcdump -ncd <ncd>`: device arc dump (4 MB), not the design's routing; unused here.

## `.nmc` format

Big-endian, unaligned. Parser: `scripts/diamond_oracle_parse.py` `parse_nmc()`; it dies unless the walk ends exactly at EOF.

- Header: `u16 F0A1`; 3 x (`u32 F0F00132`, `u16 B65D`, `u16`, `u16`) = versions (2,2),(2,2),(3,3); cstr macro name, arch (`xo2c00`), device, package, speed.
  - One extra `00` byte follows when the macro keeps no I/O comp (seen without `-io`); not present in any corpus file.
  - `u16 0100`, `u32` unix timestamp, `u16 unk` (0..14, not the PIO count), `u32 ncomps`.
- Comp: cstr name, `i32 -1`, `u8 cls` (1 = PIO, else 0), cstr type, `u8 0`, `i32 -1`, `u8 3`, `u32 len` + config (non-`#OFF` fields only) + `00`, `u16 n` x (`u16 len` + element name + `00`, `i32` logical-primitive index or -1), properties.
- Properties (comps and signals): `u32 n` x (`u16 type`, `u32 len` + name, `u8 1`, value). type 2 = u8, 3 = i32, 5 = `u32 len` + string.
- Signals: `u32 n` x (cstr name, `u32 id`, `u8 0, u8 1, u8 2`, `u32 npins` x (`u32 comp`, `i32 7FFFFFFF` x 2, cstr pin, `u32 index`), `u32 0`, properties).
  - Signal properties seen: `TW_IS_CONST_SIG`, `PAR_CLOCKSIGNAL`, `pclk_id`, `eclk_id`, `bridge2edge_clock`.
- External pins: `u16 n` x (`u32 comp`, cstr pin), then n x (cstr name, `u16 flags`); `u32 0`; `u32` (differs run to run; unknown); `char[64]` = `"//"` + zeros; `u32 0`.
- Logical hierarchy: `u16 n` x (`u32 len` + name, `i32 parent`, `u32 flags` (0 or 0x80000000), `u16 nchild` x `u32 child`).
- Routes: `u32 n` x (`u32 narcs`, `u16 signal index`, `u32 len` + space-separated SOURCE wires, `u32 len` + SINK wires). Arc i = source[i] -> sink[i]; together a tree from the driver pin wire to every load pin wire.
- Placement trailer: ncomps x (`i32 x`, `i32 y`, `u8 placed`).

Unknown fields (`unk_*` in the parse) are constant across all 2779 files except `hdr_u16` and the post-ext `u32`; none of them is used to place or route anything.

### Validation (2779 MachXO2 targets)

- Every file parses to EOF; arc counts match both string lists in every route.
- 11968/11968 ncdread comps present in the macro; 0 config differences (ncdread fields minus `#OFF` == macro config).
- 44574/44574 ncdread pin -> net pairs present as signal pins; 19498/19498 nets routed; 127622 arcs.
- `strings` view (issue #105 example) is the route strings section; the parser returns the same wires plus the source/sink pairing.

## Coordinates

- Wire names are `R<dr>C<dc>_<wire>`, relative to the **reference comp's tile** (`Using component <X> as the reference component.` in the ncd2nmc log).
- Placement trailer: comp 0 absolute, the rest relative to comp 0; `y = (max_row - row) * 14 + slot`, `x = col` (Diamond column). `max_row` from `device-db/devices.json` (12 for the 1200).
  - Checked against ncdread for 9960 slices + pads: 0 row mismatches; slices also match column and slot (slot = slice letter).
  - Pad columns vs iodb (0-based graph col): top/bottom `+1` (slot == PIO letter), left `0` (slot reversed: A=3, B=2, D=0), right `+2` (slot reversed). Counts in `checks.pio_dcol_vs_iodb`.
- Anchor used: majority of slice-pin wires (`R<dr>C<dc>_Q2_SLICE` on a net whose pin is SLICE x `Q1` at ncdread site) -> `site - (dr, dc)`; falls back to the placement trailer when a design has no slice pins (6 targets).
  - Agrees with the placement-trailer anchor in 2771/2773 voted targets. `dcma`, `eclkbridgecs`: ref comp is DCMA / ECLKBRIDGECS and its trailer tile is one column right of the routing anchor (slice pins unanimous).
  - `re_cfgspi_adc`, `re_ident_adc`: 43 votes vs 1 + 1 stray at +-1 column (a pin wire name repeated in a neighbour tile); majority used.
- Diamond column -> prjtrellis routing-graph column: `col - 1` (`devices.json` `col_bias`). Diamond row = graph row. Verified: every Diamond slice site lands on a decoded `PLC` tile (3673/3673 MODE fields compared, 0 tile errors) and `R9C11A` <-> config tile `R9C11:PLC`.

## Globals

- Global clock nets are included by default, with the whole tree: `JCLKOP_PLL -> JLPLLCLK -> VPRXCLKI -> CLKI_DCC -> CLKO_DCC -> VPRX -> HPSX -> CLKI#T_DCC -> CLKO#T_DCC -> VPTX -> HPBX -> CLK#`.
- 1099 nets carry `PAR_CLOCKSIGNAL`; all 1099 routed.
- prjtrellis names these with `G_` / `BRANCH_` / `D_` prefixes and different home tiles; 6678 Diamond wires resolve after adding `G_`, the spine/branch wires (VPRX/HPSX/VPTX/HPBX, ~1100 each) do not resolve at their Diamond tile.
- The lift drops global names (`gkey()` returns None): 2192 decoded arcs on Diamond clock nets dropped -> 1096 split clock nets. Known gap, now measured.

## Corpus layout + rerun

```
corpus/machxo2/diamond-fuzz/<target>/     (gitignored)
  ncdread.txt ncdread.log io_keep.txt routing.nmc routing.ext ncd2nmc.log
  oracle.json      comps (site, tile, slot, config, pins, prims, props), nets (pins, props, arcs, wires; absolute), checks, warnings
  decoded.config   pluribus native decode of impl1/fuzz_impl1.bit
  compare.json     per-site fields, pip / net / gkey verdicts
corpus/machxo2/diamond-fuzz/_batch_summary.json, _compare_summary.json
```

```
python3.15t scripts/machxo2_diamond_oracle.py   [--workers 16] [--only T ...] [--force]   # ~85 s
python3.15t scripts/machxo2_oracle_compare.py   [--workers 12] [--only T ...]             # ~80 s
python3     scripts/machxo2_fuzz_dictionary.py                                            # docs/machxo2-fuzz-dictionary.md
```

- Logs: `tmp/logs/machxo2_diamond_oracle.log`, `tmp/logs/machxo2_oracle_compare.log`.
- Oracle is resumable: a target is skipped while its `oracle.json` is newer than the NCD and has the current `schema_version`.
- Memory gate: workers wait while `psutil.virtual_memory().percent >= 85`, logging every 30 s.
- Tool timeout 2.5 s per call: worst observed 0.80 s (16 workers, 3 full runs) x3.

## Batch result

- 3386 target dirs: 2779 MachXO2 processed OK, 403 have no `impl1/*.ncd` (failed builds), 204 ECP5 (`sedga_*`, LFE5U-12/25/45/85F) skipped by device (header of the NCD) — ncdread alone exceeds 1 s on the 85F.
- 0 failures. Warnings: 29 `route_multi_driver` (a sink with two source arcs: edge turnaround pairs such as `H02E0501 -> H02W0500` beside an ordinary pip into the same wire), 2 `anchor_relplace_differs`, 2 `anchor_minority_votes` (above).

## Comparison: definitions

- MATCH: same fact in both. MISMATCH: both have it, values differ (pips: Diamond's sink is driven by a different decoded pip; nets: split across lift classes or merged with another Diamond net).
- LIFT_MISSING: Diamond has it, pluribus does not. ORACLE_ONLY: Diamond has it but it is outside what pluribus models or names (wire absent from the routing graph, pad internals, hard-IP fixed conns). LIFT_ONLY: decoded config arc not on any Diamond route.
- Pip kinds come from bits.db: configurable with bits, configurable with no bits (mux default, never written to a `.config`), fixed.

## Normalisation applied to Diamond wire names (counts = wire lookups)

- `col - 1` (above), always.
- `X_SLICE` -> `X` for DSU lookup: 21024 (the lifter's own `remap()` does the same).
- `G_` prefix: 6678; `BRANCH_`: 2.
- Non-canonical span segment -> hop alias at the same tile: `V02N0400@R1` -> `N1_V02N0401` (2644), `V06N..02` -> `N1_V06N..03` (645), `H06E..02/04 -> ..03` (63), `H06W..02` (14), `V02S`/`V06S` (21). Diamond names a span truncated by the die edge by the segment on its own tile; prjtrellis only has the canonical segment.
- Unresolved after all of the above: 1048 left/right-edge PIO wires named at Diamond C0 / C23 (graph col -1 / 22, off the grid; the same name exists one column in: 120 left, 928 right), the global spine/branch, PIO/IOLOGIC internals.

## Results (2779 targets)

Sites (SLICE comps, `site_field_verdicts`):

| field | MATCH | other |
|---|---|---|
| MODE | 3673 | |
| K0/K1 INIT (decoded; absent word = bits.db default 0xFFFF) | 7346 | |
| lifted LUT4 INIT (non-constant) | 2850 | |
| REGMODE, GSR, CEMUX, CLKMUX, SRMODE, LSRONMUX (decoded, bits.db default aware) | 2939 each | |
| LSRMUX | 30 | |
| CCU2 INJECT1_0/1 | 72 | |
| REG0/1 REGSET, SD (decoded) | 2996 each | |
| lifted FF sd / gsr / ce / lsr | 2996 each | |
| lifted FF regset | 2990 | **6 MISMATCH** |
| lifted FF clk net | 1135 | 1861 ORACLE_ONLY (Diamond clock net split in the lift: globals) |

Pips (Diamond route arcs + decoded arcs):

| verdict | count | detail |
|---|---|---|
| MATCH | 80532 | 39167 decoded pips; 19584 fixed conns joined in the lift DSU; 1476 `X_SLICE` pin pairs; 1476 `F->DI` (lifter models via `ff_d_source`) |
| MISMATCH | 0 | no Diamond sink driven by a different decoded pip |
| LIFT_MISSING | 2990 | 1908 `JDI*->JQ#` pad-input pips not in the .config; 1074 PLL `CLKINTFB->CLKFB` (no-bits mux, not unioned); 8 PLL fixed conns |
| ORACLE_ONLY | 44100 | 25116 hard-IP fixed conns outside the lift DSU (EBR `JDOA->JF`, pad `JA->JPADDO`, PLL, DCC); 10239 wire not in graph (global spine/branch, right-edge pads); 4858 arc not in graph (DCC `CLKI->CLKO`, `JDIA->JREFCLK`, N/S turnarounds); 3026 pad internals |
| LIFT_ONLY | 6639 | 6635 global-clock names (prjtrellis `G_`/`BRANCH_` arcs, e.g. every `G_CLKI#T_DCC->G_CLKO#T_DCC`); **4 fabric**: PLL `CLKI -> JCLKOP/JCLKOS*` in the `pll_outdivider_mux*2_refclk` targets |

Nets (19498): 17641 MATCH, 1792 MISMATCH, 51 LIFT_MISSING (DPRAM-internal `u0/WD*_INT` nets + `pllrefcs` ref mux output), 14 ORACLE_ONLY (IOLOGIC-only nets).

- MISMATCH causes: 1096 global clock tree (`global_drop`); 680 top-edge V06 span (`vspan_offdie_over2_walkback`, below); 8 PLL feedback fixed conns; 4 left-edge H06 stub (`left_stub_drop`); 2 DCC/DCM output; 2 merges in `pll_outdivider_muxa2_refclk` (`clk_c` fused with `clkop_w`: `OUTDIVIDER_MUXA2=REFCLK`, the decoded arc `CLKI_PLL -> JCLKOP_PLL` is a real PLL bypass, Diamond routes through the PLL bel as two nets).
- MISMATCH nets not involving a global clock, PLL, DCC or DCM: only the 680 + 4 above.

## gkey() workarounds vs Diamond

Method: for every decoded arc endpoint, `gkey_branch()` (mirrors `gkey()`'s conditions) names the path taken. AGREE = the rewritten key is a wire of the same Diamond net as the arc's other end. DISAGREE = rewritten key on a different Diamond net, or arc dropped while Diamond routes it, or rewritten key unused by Diamond and the net splits in the lift.

| branch | AGREE | DISAGREE | INCONCLUSIVE | Diamond evidence |
|---|---|---|---|---|
| V-span top/bottom edge flip (`vspan_edge_flip`) | 2660 | 0 | 0 | Diamond routes `V02N0400@R1 -> V02S0401@R1` (2644 arcs): the N span at the top turns into the S span one row in, exactly the flip |
| right-edge H flip (`h_right_flip`) | 80 | 0 | 0 | Diamond `H02E0500 -> H02W0501` and `H02E0601 -> H02W0602` at C22 (80) |
| left-edge H flip (`h_left_flip`) | 24 | 0 | 0 | Diamond `H02E0501 -> H02W0500` at C1 (24) |
| V-span off-die, overshoot 1 (`vspan_offdie_flip`) | 4 | 0 | 0 | |
| V-span off-die, overshoot 2 -> walk-back | 0 | **681** | 0 | Diamond: `N3_V06N0103` from row 1 is `V06N0100@R1`, which turns into `V06S0103@R3` (675 arcs). The walk-back key `V06N0103@R0` is on no Diamond route; 680 nets split (EBR clock nets `dp8kc_*`, `re_ebr_*`, ...) |
| left-edge stub drop (`left_stub_drop`) | 0 | **4** | 0 | `W3_H06W0303` at R2C2 is dropped; Diamond routes it as `H06W0301@C2 -> H06E0304@C2` (turnaround) on `out0_c` of `efb_i2c2_spi*`; net splits |
| H06E right-edge mirror, right stub drop | - | - | - | never exercised by the corpus |
| global names (`global_drop`) | 0 | 2192 | 3337 | Diamond routes the dropped arcs (clock trees); expected gap, not a workaround |
| other unresolvable names (`unresolved_drop`) | 0 | 0 | 2 | |
| `_v02_alias` (identity) | - | - | - | V02S06xx/07xx used on 3666 tile-uses, never with the V02N mate at the same tile: no evidence either way |

- The two DISAGREE rows are splits (missing joins), not fusions; both are faults: 680 + 4 nets.
- **Headline, every non-match counted as a fault:** pips 80,532 / 134,261 matched (60.0%; 53,729 faults: 2,990 missing, 44,100 not modelled/named, 6,639 extra); nets 17,641 / 19,498 (90.5%; 1,857 faults); register-clock nets 1,135 / 2,996 (37.9%). "0 pip MISMATCH" only means no pip disagreed where both sides had it.
- Diamond's turnaround arcs give the missing rules directly: top edge `V06N{i}00@R1 -> V06S{i}03@R3`; left edge `H06W{i}01@C2 -> H06E{i}04@C2`. Not applied here (`lifters/machxo2_lift.py` untouched).

## Lifter fixes from the oracle (2026-10-23, 2779 targets)

One commit each; `scripts/machxo2_oracle_compare.py` rerun after each. Fault = every non-MATCH verdict.

| category | before | after | faults before -> after |
|---|---|---|---|
| pips | 80,532 / 134,261 = 60.0% | 80,532 / 134,261 = 60.0% | 53,729 -> 53,729 (every pip verdict unchanged) |
| nets | 17,641 / 19,498 = 90.5% | 18,325 / 19,498 = 94.0% | 1,857 -> 1,173 |
| register clock nets | 1,135 / 2,996 = 37.9% | 1,876 / 2,996 = 62.6% | 1,861 -> 1,120 |
| FF regset | 2,990 / 2,996 | 2,996 / 2,996 | 6 -> 0 |
| FF srmode (new check) | not checked | 2,996 / 2,996 | 0 |
| gkey `vspan_offdie_over2_walkback` | 0 AGREE / 681 DISAGREE | 681 AGREE / 0 | 681 -> 0 |
| gkey `left_stub_drop` | 0 AGREE / 4 DISAGREE | 4 AGREE / 0 | 4 -> 0 |

- Field-by-field summary diff: only the rows above change; every other site/pip/gkey count is identical (no MATCH lost, no fault category rose).
- Net MISMATCH 1,792 -> 1,108 = 1,096 global clock + 8 PLL feedback + 2 DCC/DCM + 2 `pll_outdivider_muxa2_refclk`.
- Fixes:
  1. FF REGSET: missing `REG*.REGSET` = bits.db default (`SET`), read via `plc_enum_defaults()`; was hardcoded `RESET`. ECP5 (`ecp5_lift.py:502`) has the same hardcoded `RESET` while ECP5 `bits.db` also defaults `SET`; not changed (no ECP5 SET register evidence run).
  2. SRMODE: tile enum `LSR{slice}.SRMODE`, `ASYNC` | `LSR_OVER_CE`. Diamond config strings equal the bits.db option names (corpus: 2,905 `ASYNC`, 34 `LSR_OVER_CE`); lifted FF `srmode` matches 2,996/2,996. `RFF` model is async for `ASYNC`.
  3. gkey V-span off-die by 2 rows: key = opposite-letter span, same index+segment, 2 rows inward (top row 1: `N3_V06N{i}03` -> `V06S{i}03@R3`, `N3_V06S0103` -> `V06N0103@R3`; bottom row 11: `S3_V06N0103` -> `V06S0103@R9`). Arcs: 674 + 5 + 1 + 1 over `dp8kc_*`, `re_ebr_*`, `fifo8kb_x18`, `pic_b0_hiio_hstl18_i`.
  4. Left stub: `W3_H06W{i}03` at col 2 (1 col off die) = `H06E{i}03` at col 0 (Diamond `H06W0301@C2 -> H06E0304@C2`); 4 arcs in `efb_i2c2_spi*`.
- Hantek V02 (`run_pipeline.py`, per commit): REGSET and SRMODE commits leave `2611/1280 LUTs, 1108 FFs, 4341 nets`; V-span rule -> 4274 nets (67 split nets rejoined); left-stub rule -> 1112 FFs, 4262 nets. The 4 new FFs (`ff_r3c2_A0`, `r3c2_B0`, `r5c2_A1`, `r8c2_C0`) are registers whose Q previously fell on the dropped stub and was treated as unused.
- V02 register modes after the fix: 34 registers are `REGSET=SET` (were all lifted RESET); 871 RESET/ASYNC, 207 RESET/LSR_OVER_CE.
- `lifter_equiv_corpus.py` before and after each fix: 459 equivalent, 0 not equivalent, 204 error (ECP5 `sedga_*`, unchanged).

## Other findings

- **Lifter FF REGSET default is inverted.** bits.db: `.config_enum SLICEA.REG0.REGSET SET` (absent from the .config = SET). `recover_netlist()` uses `senum.get("REG{j}.REGSET", "RESET")`. All 6 Diamond `REGSET=SET` registers in the corpus (`ff_*async_pre*` targets) lift as RESET; the decoded enum compare (default-aware) matches 2996/2996.
- `SRMODE` lives in tile enum `LSR{slice}.SRMODE` (default `LSR_OVER_CE`), not under `SLICEx`; the lifter does not model SRMODE.
- Pad input pip `JDIA -> JQ0` (top edge, bits.db `PIC_T0` `.mux S1_JQ0 / JDIA F2B9`): F2B9 is also the IOLOGIC-select bit of `JDIA <- INDDA_TIOLOGIC`, so the bypass routing Diamond uses never appears in a decoded `.config` (1908 arcs). The lifter covers it with `pad_fabric_node()`.
- Constant-1 LUTs (Diamond `H0=1`, 1149) have no INIT word in the .config: the PLC bits.db default is all ones.

## Spot checks (raw -> oracle.json -> lift)

1. `re_iostd_LVCMOS25D_FAILSAFE_d4` net `d_c` (SLICE_0.Q0 -> SLICE_0.D0 + pad `d`): ncdread pins `Q0`, `D0` on SLICE_0 @ `R9C11A`, `PADDO` on `d` @ pin 36. nmc route (ref `d`): `R-3C0_Q0_SLICE R-3C0_Q0 R-3C0_V01S0100 R-1C0_V02S0701 R-1C0_JA2 R0C0_JPADDOC ...`; anchor R12C11 -> `R9C11_Q0 -> R9C11_V01S0100 -> R11C11_V02S0701 -> R11C11_JA2 -> R12C11_JPADDOC`. Lift: decoded `R9C11:PLC arc: H00L0200 Q0`, `CIB_R11C11 arc: JA2 V02S0701`; all fabric wires in lift net `n2`; verdict MATCH. Pad wires `JPADDOC`, `PADDOC_PIO` ORACLE_ONLY.
2. `efb_i2c1_i2c2_spi_tc_ufm` net `wbdato_w_1` (EFB.WBDATO1 -> SLICE_0.C1 @ `R2C4D`): `R1C4_JWBDATO1_EFB -> R1C6_JF1 -> R2C6_V02S0101 -> R2C5_H02W0101 -> R2C4_C7 -> R2C4_C7_SLICE` (slice D input C1 = tile wire C7). Decoded arcs `S1_V02S0101 JF1`, `W1_H02W0101 V02S0101`, `C7 E1_H02W0101`; lift net `n11` for every fabric wire; MATCH.
3. `dp8kc_x1` net `clk_c` (pad 88 -> SLICE_0.CLK, EBR CLKA/CLKB): `R0C12_JDIA -> R1C12_JQ0 -> R1C13_H01E0001 -> R1C13_V06N0100 -> R3C13_V06S0103 -> R6C12_H02W0301 -> ...`. Lift: `JQ0`, `H01E0001` in `n4`; `V06S0103` onward in `n3`; `V06N0100@R1` (= config `N3_V06N0103` at row 1) walks back to `V06N0103@R0`, a key on no Diamond route -> MISMATCH (split). The walk-back DISAGREE above.

## Verified vs assumed

- Verified: nmc grammar (full corpus to EOF), arc direction (driver wire at the tree root in every net), anchor (slice-pin vote vs placement trailer), placement-trailer formula (9960 comps), Diamond `col - 1` = graph column, ncdread/nmc completeness, every count above.
- Assumed: meaning of the `unk_*` fields and the `hdr_u16`; that `pclk_id` / `PAR_CLOCKSIGNAL` mean primary clock; the segment-alias direction rule beyond the spans listed (only spans the corpus uses were exercised).
- Not covered: MachXO2 devices other than the 1200 (no corpus), ECP5 `.nmc` (204 targets skipped), timing.
