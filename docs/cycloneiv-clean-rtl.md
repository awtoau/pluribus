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
- Counters: `CNT_UP` / `CNT_DOWN` / `CNT_UPDOWN` / `CNT_SEL`: chain whose bit i is the FF fed by sum i (own Q is an operand), other operand constant or one shared signal; next = R + K(s). Enable / clears / load are the bundle's FF control set. A free head's bit 0, or a shared signal that is itself a toggling FF, is bit 0 of the register. `CNTL`: counter built from LUTs (patterns.lut_counters, exact check), per-bit statements kept.
- Registers: FFs with equal clock / polarity / enable / aclr / sclr / sload form one always block (`REG`, chunks of 32); chain-fed register (`REG_CHAIN`); `SHIFT` = longest-path decomposition of the D-copy forest (taps do not break a path; loadable stages: mux with one shared select set), `LFSR` = shift whose head D is a function of >= 2 stages of its own path.
- Cones: single-fanout LUT trees merged up to 6 leaves, support reduced, then `MUX<2^k>`, `XOR`, `SOP` (exact Quine-McCluskey), `TT`. A mux construct (report key `muxes`) = mux-shaped cones joined by data flow that share a select set (bus) or form a tree of >= 3; a lone mux-shaped cone is an expression. Load muxes inside a shift register are not counted.
- `FSM`: strongly connected group of register FFs (2..24 state bits, one control set, no load); reachable states from power-up 0 enumerated (<= 64) with next-state per state over the inputs its cone still depends on after constant propagation (<= 10 per state), so the total input count is unbounded; binary / gray / one-hot alike. `case` lists reachable states only (closed under all inputs, exact from reset).
- M9K / MAC / PLL text is the emit's own block text with names rewritten (tracks emit.py), long lines split. Pads: `io_<ball>`.
- Combinational assigns carry the `LUT_DELAY` macro (empty by default), same as the flat emit.

## Validation (rtl_check)
- (i) iverilog, same vectors (hold-safe `-DLUT_DELAY=#1`, 2 ns compare spacing, when an async clear or clock is driven by logic; zero-delay glitches differ between a vector update and per-FF updates, the function does not). Status `x_in_flat` = every mismatch is an x in the flat model (INIT-indexed LUT with an x on a pin its INIT ignores), not counted as pass: RTL vs flat emit (all output pads); `--vo`: RTL vs post-fit .vo through `emit_sim.run_one`, next to the flat-vs-.vo baseline (an inherited emit mismatch shows in both).
- (ii) structure vs `src/top.v`: register bits, adders / subtractors (count, width), comparators, MAC, M9K, counters, FSMs -> matched / missing / extra / wrong. Random-LUT specimens have no word-level source structure.
- (iii) lines and constructs, RTL vs flat.
- Results: issue #165 comments (numbers with date and sample).
