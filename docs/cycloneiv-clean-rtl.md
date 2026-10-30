# Cyclone IV GX clean RTL lift: flat netlist -> structured Verilog (#165)

Code: `lifters/cycloneiv_clean/rtl.py` (`Lift`, `lift(nl)`), CLI `scripts/cycloneiv_clean_rtl.py`, set `scripts/cycloneiv_clean_lift_ready.py` -> `reference/lift_ready.tsv`, validation `scripts/cycloneiv_clean_rtl_check.py`. Test: `tests/cycloneiv_clean/test_rtl.py`.
Input is the emit `Netlist` (read-only); no decoder or emit hunk is touched. Structure only: no statistics, no learned patterns. Every construct carries a `[R:<rule>]` tag; unrecognised pieces stay flat (`FLAT_LUT`).

## Lift-ready set
- Gate run 26 (`gx150.db` `gate_results`): pips, nets, lut_init, register_clock each 0 missing / extra / wrong, AND structural check (`emit_check.score_design`) lut_site, ff_site, ff_clock, lut_carry each 0 missing / extra / wrong.
- Pins reported separately (never a blocker). `reference/lift_ready.tsv`: `name<TAB>group` (primary = EP4CGX150DF31C7, other-package, other-die, no-device-key).

## Rules
- Carry chain: per LE the fitter stores sum = X^Y^c and cout = maj(X,Y,c) ^ po, polarity po alternating per stage; X/Y = operand bit, inverted operand bit, or constant. Chain accepted only if every LE fits one form with common operand polarity (ADD / ADDC (constant operand) / SUB). Trailing X=Y=0 LE = carry collector.
- `CMP_GE` / `CMP_GT`: subtract chain whose only used output is the final carry. `CARRY`: prefix carry wire, only when a non-chain reader uses an inner carry. `CNT_UP` / `CNT_DOWN`: chain whose operand A is the register it feeds, operand B constant.
- Registers: FFs with equal clock / polarity / enable / aclr / sclr / sload form one always block (`REG`, chunks of 32); chain-fed registers ordered by chain bit (`REG_CHAIN`); `SHIFT` = path of >= 3 FFs whose D is the previous Q with single reader.
- Cones: single-fanout LUT trees merged up to 6 leaves, support reduced, then `MUX<2^k>` (k selects, literal data), `XOR`, `SOP` (exact Quine-McCluskey, smaller of f / ~f), `TT` (indexed truth table above 16 literals). Buffer LUTs alias their input; constant LUTs fold.
- `FSM`: strongly connected FF group (2..6 state bits, <= 5 other inputs, no shift edge inside) as an exact `case` over all 2^n states; reachable-from-reset count in the comment.
- M9K / MAC / PLL text is the emit's own block text with names rewritten (tracks emit.py). Pads: `io_<ball>`.

## Validation (rtl_check)
- (i) iverilog, same vectors: RTL vs flat emit (all output pads); `--vo`: RTL vs post-fit .vo through `emit_sim.run_one`, next to the flat-vs-.vo baseline (an inherited emit mismatch shows in both).
- (ii) structure vs `src/top.v`: register bits, adders / subtractors (count, width), comparators, MAC, M9K, counters, FSMs -> matched / missing / extra / wrong. Random-LUT specimens have no word-level source structure.
- (iii) lines and constructs, RTL vs flat.
- Results: issue #165 comments (numbers with date and sample).
