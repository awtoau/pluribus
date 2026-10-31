# Cyclone IV GX clean RTL lift: flat netlist -> structured Verilog (#165)

Code: `lifters/cycloneiv_clean/rtl.py` (`Lift`, `lift(nl)`), CLI `scripts/cycloneiv_clean_rtl.py`, set `scripts/cycloneiv_clean_lift_ready.py` -> `reference/lift_ready.tsv`, validation `scripts/cycloneiv_clean_rtl_check.py`. Test: `tests/cycloneiv_clean/test_rtl.py`.
Input is the emit `Netlist` (read-only); no decoder or emit hunk is touched. Structure only: no statistics, no learned patterns. Every construct carries a `[R:<rule>]` tag; unrecognised pieces stay flat (`FLAT_LUT`).

## Lift-ready set
- Gate run 26 (`gx150.db` `gate_results`): pips, nets, lut_init, register_clock each 0 missing / extra / wrong, AND structural check (`emit_check.score_design`) lut_site, ff_site, ff_clock, lut_carry each 0 missing / extra / wrong.
- Pins reported separately (never a blocker). `reference/lift_ready.tsv`: `name<TAB>group` (primary = EP4CGX150DF31C7, other-package, other-die, no-device-key).

## Rules
- Carry chain: per LE the fitter stores sum = X^Y^c and cout = maj(X,Y,c) ^ po (polarity po alternating per stage); X/Y = operand bit, inverted operand bit, or constant. Which pin carries which operand changes between bits; orientation = shared signal -> B, on a tie the inverted operand -> B. Accepted only if every LE fits one form with common operand polarity (ADD / ADDC / SUB).
  - Head LE may be a pure carry generator (sum unused or not an adder bit): `free_head`, its sum stays ordinary logic. LEs whose sum is unused (compare chains) are checked on cout only. A last LE that fits no form (result gating LUT) is split off (`tail_free`), its carry-in is the chain carry out.
  - `CMP_GE` / `CMP_GT`: subtract chain whose only used output is the final carry (a <= b, a < b etc. = polarity of that carry). `CARRY`: prefix carry wire.
- Mixed polarity: a chain whose operand bits carry different inversions (fitter polarity choice per signal) is accepted as `A + B` over effective literals (`~sig` printed per bit); covers negate / constant-minus-x chains. Flag `mixed` in the chain record.
- Dead flops: a sum read only by the D pin of a flop whose output nobody reads is treated as unread (not observable), same as a sum with no reader.
- Head ambiguity: the head LE fits several (polarity, constant carry-in) forms; each is tried until the whole chain fits. Constant LE pins take only their constant value in the form check.
- Counters: `CNT_UP` / `CNT_DOWN` / `CNT_UPDOWN` / `CNT_SEL`: chain whose bit i is the FF fed by sum i (own Q is an operand), other operand constant or one shared signal; next = R + K(s). Enable / clears / load are the bundle's FF control set. A free head's bit 0, or a shared signal that is itself a toggling FF, is bit 0 of the register. `CNTL`: counter built from LUTs (patterns.lut_counters, exact check), per-bit statements kept.
- Registers: FFs with equal clock / polarity / enable / aclr / sclr / sload form one always block (`REG`, chunks of 32); chain-fed register (`REG_CHAIN`); `SHIFT` = longest-path decomposition of the D-copy forest (taps do not break a path; loadable stages: mux with one shared select set), `LFSR` = shift whose head D is a function of >= 2 stages of its own path.
- Cones: single-fanout LUT trees merged up to 6 leaves, support reduced, then `MUX<2^k>`, `XOR`, `SOP` (exact Quine-McCluskey), `TT`. A mux construct (report key `muxes`) = mux-shaped cones joined by data flow that share a select set (bus) or form a tree of >= 3; a lone mux-shaped cone is an expression. Load muxes inside a shift register are not counted.
- `FSM`: strongly connected group of register FFs (2..24 state bits, one control set, no load); reachable states from power-up 0 enumerated (<= 64) with next-state per state over the inputs its cone still depends on after constant propagation (<= 10 per state), so the total input count is unbounded; binary / gray / one-hot alike. `case` lists reachable states only (closed under all inputs, exact from reset).
- Pattern modules (`patterns.lfsr_groups`, Fibonacci / Galois, medium or high confidence): one bundle in stage order printed as its own module `lfsr<n>_<table name>_<k>` / `crc<n>_<table name>_<k>` (word-parallel / serial Galois groups with a CRC table match) or `lfsr<n>_<form>_taps_<..>`; outside signals are `in_<k>` ports. Header comment: stages, form, taps, characteristic polynomial, external inputs, table match + orientation. Function unchanged (same always block).
- M9K / MAC / PLL text is the emit's own block text with names rewritten (tracks emit.py), long lines split. Pads: `io_<ball>`.
- Combinational assigns carry the `LUT_DELAY` macro (empty by default), same as the flat emit.

## Validation (rtl_check)
- (i) iverilog, same vectors (hold-safe `-DLUT_DELAY=#1`, 2 ns compare spacing, when an async clear or clock is driven by logic; zero-delay glitches differ between a vector update and per-FF updates, the function does not). Status `x_in_flat` = every mismatch is an x in the flat model (INIT-indexed LUT with an x on a pin its INIT ignores), not counted as pass: RTL vs flat emit (all output pads); `--vo`: RTL vs post-fit .vo through `emit_sim.run_one`, next to the flat-vs-.vo baseline (an inherited emit mismatch shows in both).
- (ii) structure vs `src/top.v`: register bits, adders / subtractors (count, width), comparators, MAC, M9K, counters, FSMs -> matched / missing / extra / wrong. Random-LUT specimens have no word-level source structure.
- (iii) lines and constructs, RTL vs flat.
- (iv) `scripts/cycloneiv_clean_rtl_chain_check.py`: every recognised chain vs the LUT-level chain on random operand assignments (sums read, carry signals with polarity); negative control (flipped carry-in) fails every chain.
- Flat-LUT classification: `scripts/cycloneiv_clean_rtl_left.py` (chain failure reason, chain length histogram).
- (v) `scripts/cycloneiv_clean_pattern_corpus_check.py` (#186): known-truth specimens independent of the DJI image -- one small behavioral-Verilog construct per rule tag (adder, subtractor, comparator, counter, shift register), built fresh with Quartus each run, lifted, checked that `rtl.lift()`'s report tags it correctly and leaves `flat_lut_left == 0`. Closes the gap F-021 exposed: a recognizer rule can regress with nothing catching it if no corpus specimen exercises that exact construct (previously only the DJI image's own behavioral test did). 2026-10-31: 5/5 pass, each specimen tags only its own construct (no cross-contamination). Not run in the fast/full gate (real Quartus builds, ~2-3 min); run on demand or when touching `rtl.py`'s rule set.
- Results: issue #165 comments (numbers with date and sample).

## hl corpus score (2026-10-30, 153 designs, matched / missing / extra / wrong; `scripts/cycloneiv_hl_score.py`, split by seed parity)
- Lifter changes were made looking at train (even seeds, 74 designs) only; held-out (odd seeds, 79) run once for before and once after. `scripts/cycloneiv_hl_iter.py` = cached-netlist iteration harness.

| key | train before | train after | held-out before | held-out after |
|---|---|---|---|---|
| reg_bits | 11170/423/114/0 | 11170/423/114/0 | 14515/371/69/0 | 14515/371/69/0 |
| counters | 0/75/0/0 | 55/20/0/0 | 0/67/0/0 | 47/20/0/0 |
| adders | 13/19/12/2 | 32/1/15/1 | 23/24/15/1 | 45/3/13/0 |
| subtractors | 0/3/0/0 | 3/0/13/0 | 1/11/0/0 | 9/3/10/0 |
| comparators | 0/14/0/0 | 12/2/0/0 | 0/24/0/0 | 19/5/0/0 |
| fsms | 5/16/0/0 | 21/0/0/0 | 5/16/0/0 | 21/0/0/0 |
| shift_registers | 83/163/38/0 | 233/13/3/0 | 106/171/33/0 | 269/8/3/0 |
| muxes | 8/0/255/0 | 7/1/1/0 | 7/1/282/0 | 7/1/5/0 |
| m9k | 87/7/1/0 | 87/7/1/0 | 89/7/2/0 | 89/7/2/0 |
| mac | 19/1/0/0 | 19/1/0/0 | 143/2/0/0 | 143/2/0/0 |
| all keys | 11385/721/420/2 (90.9%) | 11639/468/147/1 (95.0%) | 14889/694/401/1 (93.1%) | 15164/420/102/0 (96.7%) |

- RTL vs flat: train 73 pass + 1 `x_in_flat` (was 69 pass / 5 fail), held-out 78 pass + 1 `x_in_flat` (was 75 / 4). The 4 async-clear `regs` failures were zero-delay glitch order, not function: pass under hold-safe delays (also vs .vo).
- Remaining misses are not lifter limits: identical counters merged by Quartus (ram / rom / mix pairs), registers absorbed into M9K / MAC (reg_bits), 4-bit adders / comparators built from plain LUTs (no carry chain), fifo occupancy arithmetic (extra adders / subtractors, real logic absent from the manifest).

## hl corpus, second pass (2026-10-30, netlists rebuilt at the same HEAD; matched / missing / extra / wrong)
- Changes: mixed-polarity chains, dead-flop sums, head ambiguity, pattern modules. Edits looked at train (even seeds) only; held-out (odd) run before and after.

| split | before | after |
|---|---|---|
| train (74) | 11639/468/147/1 | 11640/467/147/1 |
| held-out (79) | 15164/420/102/0 | 15169/415/106/0 |

- Held-out arithmetic: counters 47 -> 49 matched, subtractors 9 -> 12 matched; extra subtractors 10 -> 13 and adders 13 -> 14 (chains the manifest has no entry for).
- Flat LUTs left in the hl set: held-out `bigadd_1` 195 -> 0, `counter_9` 24 -> 0, `mix_3` 32 -> 0, `ram_5` 7 -> 0.
- RTL vs flat: train 73 pass + 1 `x_in_flat`, held-out 78 pass + 1 `x_in_flat` (unchanged).
- Gate tier `hl` recorded: `gate_runs` id 43 (153 designs, no regression vs run 36).

## Third-party image (counts only; 2026-10-30, same HEAD decoders, before = rtl.py at HEAD a080869a1)
| key | before | after |
|---|---|---|
| LUTs / FFs | 89,282 / 36,993 | same |
| adders / subtractors / comparators | 586 / 180 / 108 | 1,377 / 353 / 108 |
| counters / FSMs | 224 / 21 | 226 / 21 |
| shift registers (bundles) | 275 | 267 (259 SHIFT + 1 LFSR + 7 LFSR modules) |
| pattern modules (LFSR / CRC) | 0 | 8 (7 + 1) |
| carry chains recognised | 874 | 1,838 |
| flat LUTs left (`FLAT_LUT`) | 10,178 | 418 |
| RTL lines | 174,994 | 141,432 |
| verilator `--lint-only` (RTL) | 0 errors | 0 errors, 2 warnings |

- Flat LUTs left before: 1,004 failed chains: operand polarity mixed or negate (R6/R7/R8: 5,013 LUTs), no operand form (5,165: dead-flop sums and ambiguous head forms). After: 40 chains, all `no_operand_form` (multi-LE result tails after the adder bits, AND-gated operand incrementers, bits whose second operand repeats one signal).
  - **Per-category split was never recorded until now** (`scripts/cycloneiv_clean_rtl_left.py` classifies only by `why`, not by LE shape). Exact classification of the 418 (39 chains, not 40 -- `scripts/cycloneiv_clean_rtl_left.py` under-counted one): by where the chain's adder-form fit first fails (`fail_at` vs chain length `n`) -- 31 chains / 332 LUTs fail at the head or within the first 2 LEs (operand pair repeats a prior bit's pair, or no adder form fits any head candidate: the "AND-gated operand incrementer" / "second operand repeats one signal" categories, still open, below); 8 chains / 86 LUTs fail only in their last 2-5 LEs, with every earlier LE fitting a clean adder (the "multi-LE result tail" category, closed below).
- SHIFT bundles fell 274 -> 259: stage-0 flops fed by a now-recognised chain sum belong to `REG_CHAIN` registers (137 -> 339), leaving a 2-stage tail below `SHIFT_MIN`.
- Chain check (`scripts/cycloneiv_clean_rtl_chain_check.py`): 2,061 chains, 0 mismatches over 64 random assignments each (791 mixed polarity).

## Image RTL vs flat simulation (2026-10-31, #165)
- Constant output pads (`io["const"]`, 6 on the image, 4 of them 1) are driven as in the flat emit; the RTL had left them `// UNDECODED`.
- `Lift.ffmap` / `rtl.lift(nl, ffmap=dict)`: flat FF name -> RTL register bit, for probes.
- `scripts/cycloneiv_clean_rtl_image_compare.py` (lift / run [--spi]): flat and RTL simulated with the same testbench, FF snapshots through the map. 20,000 clocks, 53 output pads, SPI program (frame active low, `+cs_active=0`): 0 differing rows, 0 differing FFs at all 23 snapshots; AA7 high in 640 rows in both. Idle run: 0 differing rows.
- The earlier "AA7 never high in the RTL" came from the testbench: `cycloneiv_clean_image_sim.py run --src rtl` builds without probes, so no SPI program was driven; the default `+spi` frame polarity (active high) loads nothing in either model.
- Image netlist rebuilt at HEAD: 89,282 LUTs, 35,873 FFs; RTL 139,293 lines, adders 1,377, subtractors 198, comparators 260, counters 226, FSMs 21, flat LUTs left 418.

## Multi-LE tail strip (2026-10-31, #165): 418 -> 332 flat LUTs

- **Rule (`RTL-001`, `analyse_chain` in `rtl.py`):** the existing single-LE `tail_free` only retried with `full[:-1]` when the whole-chain fit failed exactly at the last LE (`fail_at == len(full) - 1`). Generalised to strip 1, 2, 3, ... trailing LEs (stopping at the shortest strip whose remaining prefix fits a complete adder form), closing chains whose result tail is itself 2+ LEs: a non-adder result LUT (reads the chain's final carry plus one extra flag/signal) followed by one or more pure carry-buffer/inverter collector LEs that only read a constant pair plus carry-in. Source: structural, derived directly from the already-decoded per-chain `fail_at` / adder-form fit in `_analyse`/`_analyse1` -- no new guess, same truth-table-exact acceptance test as the existing single-LE case, just tried at more strip lengths.
- Closed 8 of the 39 `no_operand_form` chains (86 LUTs): chain lengths 4-16, needing strip 2 (x4), 3 (x2), 4 (x1), 5 (x1). Example (real LE shapes, image chain index 1835): a 10-bit ADD/SUB chain (`mixed` polarity) + a result LUT (`sum = ~(a^b^c)`, `cout = ~c & (a|b)` -- not `maj()`, so correctly rejected as an adder bit) + a pure carry buffer (`sum = cout = ~c`) reading the result LUT's carry-out by name.
- **Emission bug found and fixed in the same change:** a tail LE's own carry-out (`co_x_y_le`) can be read by name by the *next* tail LE (chained tails), not only by a cone elsewhere. `self.cone` only ever holds a LUT's *sum* truth table; before this fix `need_closure` had no case for a bare `co_*` reference into a `normal()` (non-chain, non-opaque) LUT, so the wire was referenced but never declared -- caught by a verilator build of the full image (`Can't find definition of variable: co_101_18_10`), not by the chain-check (which only tests chain-internal relationships, never the surrounding RTL text). Fixed with a new `need_tail_co` set + emission block, same INIT-indexed formula as the existing opaque-LUT carry-out line. Regression test `test_multi_le_tail_chained_carry_out` (`tests/cycloneiv_clean/test_rtl.py`) reproduces it with chain 5's real LE shapes.
- **Count discipline:** 332 LUTs remain genuinely opaque (`need_opaque`, unresolved sum -- the number comparable to the old 418 headline). The 8 closed chains' tail LEs (23 LUTs) mostly resolve their *sum* through the ordinary SOP/XOR cone path (not flat); only their *carry-out* wire still needs a `[R:FLAT_LUT] tail_free carry-out` line (15 of 23, confirmed disjoint from the 332 by `co_*` vs `lc_*` naming) because that function has no clean closed form worth a named rule. `rtl.lift()`'s `flat_lut_left` stat (332 + 15 = 347) counts both; `scripts/cycloneiv_clean_rtl_left.py` (LUT-level `need_opaque` only) reports 332.
- **Verification (per the project's behavioral-verification rule, both before and after):**
  - Chain-check (`scripts/cycloneiv_clean_rtl_chain_check.py`, 64 random vectors/chain): before 2,061 chains / 0 bad; after 2,069 chains / 0 bad (791 -> 796 mixed-polarity, +8 matches the 8 newly-closed chains exactly).
  - **Negative control added** (`--negative-control`, flips `ch["c0"]` on every chain before checking -- the doc's claimed "flipped carry-in" control did not exist in the script until now): 0 ok / 2,069 bad with the flag, both before and after this change -- confirms the check genuinely distinguishes right from wrong, not just "ran without crashing".
  - Full-image RTL-vs-flat simulation (`scripts/cycloneiv_clean_rtl_image_compare.py run --spi`, 20,000 clocks, SPI program): before and after this change, 0 differing rows, 0 differing FFs at all 23 snapshots. `verilator --lint-only`: 0 errors both before and after (the build failure during development, from the emission bug above, was caught here and fixed before this number was taken).
  - Unit tests (`tests/cycloneiv_clean/test_rtl.py`): 8/8 pass, including two new tests built from real image LE shapes (`test_multi_le_tail_strip`, `test_multi_le_tail_chained_carry_out`).
- **Not closed (31 chains, 332 LUTs, all still `no_operand_form`):** every remaining failure occurs at or within the first 1-2 LEs of the chain (not a tail), and inspection of individual LE truth tables shows at least two genuinely distinct non-adder primitives: (a) an LE whose `cout` is a real, non-`maj()` function of its two operands and incoming carry (e.g. `cout = ~(c & (a^b))`, confirmed exactly by exhaustive truth-table check, present at the second LE of 16 of the 31 chains) where the SAME broadcast signal is read as the "B" operand at every bit position of the chain (the "second operand repeats one signal" / conditional-increment category) -- the per-bit arithmetic meaning of this primitive was not derived to the exact, simulation-matched standard this project requires before adding a recognizer (candidate formulas tried and falsified: broadcast XOR, broadcast add/sub-by-mask, every single-input-inverted `maj()` variant); (b) chains whose second LE reads the exact same operand pair as a later LE (the "AND-gated operand incrementer" category), only sketched structurally, not yet reduced to an exact per-bit rule. Both remain `FLAT_LUT` rather than risk a wrong tag -- per the project's rule, a plausible-looking but unverified recognizer is worse than leaving the LUT flat.
