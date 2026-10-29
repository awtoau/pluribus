# Cyclone IV bit hunter (#141)

Search for build pairs that differ by exactly ONE configuration cell. Script: `scripts/cycloneiv_bit_hunter.py`.
Raw cram-plane diffs only (no decoder); threads via `build_pool` (lease + box cap); cache `tmp/bit_hunter/` (not in git).

## Method
- Variant = parameter dict; one knob changed from a base. Name = hash of params (`gxbh_<hash>`).
- Plane cache = diff-from-base (`A` = keys only in variant, `R` = keys only in base). Distance(i, j) = |tagged-set symmetric difference|.
- Family A: `u0 -> u1` in X10Y10, LOCAL_LINE + port forced by RCF. Family B: ONE test LE + 7 idle control-source LUTs in the same LAB.
- Family B: the base is built free once (`boot`), its routing.rcf back-annotates the base and every variant (same router area).
- Quartus rejects a LUT mask that depends on an unconnected port: all unused ports are tied to the input pin (`ina`) or a knob constant.
- Control: `AUTO_GLOBAL_CLOCK` / `AUTO_GLOBAL_REGISTER_CONTROLS` off, `SEED 1`; sload needs asdata.
- Adaptive: pairs at distance 2-3 get in-between variants (one component, or one mask bit, moved toward the partner); budget 100.
- Null controls run first and gate the batch: renamed design, other seed -> diff empty (0 cells, 5 pairs).
  - First attempt failed: free-fit base vs back-annotated base differ by 2 cells; fixed by the `boot` build. The pair stays in the table.
- Evidence: `record` writes one row per (cell, knob) as `bit_hunter:<knob>` (spec = plane i, base = plane j, n_objects 1); meta has frame, v, tile, (df, dv).

## Rerun
```
python3.15t scripts/cycloneiv_bit_hunter.py batch1 --jobs 22   # nulls, then all knobs
python3.15t scripts/cycloneiv_bit_hunter.py batch2|batch3 --jobs 22
python3.15t scripts/cycloneiv_bit_hunter.py adapt --budget 100 --depth 3
python3.15t scripts/cycloneiv_bit_hunter.py replicate           # distance-1 pairs rebuilt at X58Y30
python3.15t scripts/cycloneiv_bit_hunter.py report|record       # summary.json / evidence rows
```

## Results (2026-10-29, 851 builds ok, 8 refused by the fitter)
| item | result |
|---|---|
| calibration: sink LUT-mask bit | 16 / 16 variants = exactly 1 cell |
| calibration: source LUT-mask bit | 16 / 16 variants = exactly 1 cell |
| single cells isolated at X10Y10 | 33 = 32 LUT-INIT (calibration) + 1 clock-polarity |
| replicated at X58Y30 (same pairs rebuilt) | 24 / 33 land on the same (df, dv); 9 sink-INIT cells shift by (+-1..3) in (df, dv) |
| refused by fitter | FF power_up=high (needs an inverter in the same LE), 3 sload variants |
| unreachable here | any control-net connection (ena, aclr, sclr, clk source): 20-100 cells each |

Single cell with a stated role beyond LUT-INIT: `clk` vs `~clk` (same source LE, FF clocked directly or inverted) flips exactly one
cell, tile-relative (df -6, dv -30) = the LAB clock-polarity cell (inventory class 1c). Holds for source KA and KB.

Hit rate per knob (exactly 1 cell vs base): LUT mask (sink) 16/48 (the rest are multi-bit masks), LUT mask (source) 16/16,
clock polarity 2/2; all others 0 (src LE 0/8, snk LE 0/14, port 0/1, tie 0/6, ff 0/1, ena/aclr/sclr/clk-source 0/50).

## Named pairs, diff cell count (one-LE LAB, same back-annotated routing)
| pair | cells |
|---|---|
| null: renamed, other seed | 0 |
| free-fit base vs back-annotated base | 2 |
| FF off / on (clk from same-LAB LUT) | 45 |
| FF fed from LUT / from asdata+sload=1 | 0 (fitter emits identical bits) |
| clk KA / ~KA (polarity) | **1** |
| clk KA / KB (other source LE) | 32 |
| ena absent / present (E) | 46 |
| ena tied 1 / absent | 0 |
| ena tied 0 / absent | 93 (identical to sclr tied 1) |
| ena E / ~E | 89 (inverter is a LUT, no polarity cell in the LAB) |
| aclr absent / present; high / low | 64; 61 |
| sclr absent / present; high / low | 52; 21 |
| sclr S vs aclr S (same net, type only) | 89 |
| ena KB vs aclr KB (same net, other control port) | 7 (8 for `ina`): port-select cells |
| LE slot 0 vs 1 / 7 / 15 | 60 / 62 / 68 |
| output comb / FF; FF / both taps | 45; 96 |
| input A used / tied 0 / tied 1 (mask AAAA) | 14 / 14 |
| input B ina / tied 0 / open | 6 / 2 (ina vs open) |
| input A from pin / from same-LAB LE | 43 |
| clk from LUT / from pin | 103 |
| clk pin local / global | 0 |
| fan-out 1 / 2 (dangling load) | 0 |

- Polarity: only the clock has a polarity cell (1 cell). ena/aclr/sclr/sload inversion is a logic inverter, not a LAB cell.
- LOCAL_LINE grid (480 variants, all legal src x snk x port): port-only change = 4 cells (45 pairs) or 8 (195 pairs);
  source-only 22-24, sink-only 22-60 (ties to `ina` add routing); no distance-1 pair, no cell of the 305 same-LAB set isolated.

## Not reachable with these knobs
- Control connections route a LUT output through LAB local lines into the control mux: 20-100 cells per connection, no partial state.
  Constant ties are absorbed (tie 1 = absent) or restructure the FF (tie 0).
- LOCAL_LINE select cells: a source or sink move always flips the LE-used and tied-port routing cells too.
- Next: base with unconnected ports (needs masks that ignore them), fan-out splits (spec adds a second sink on the same LL).

## Round 2 (2026-10-29)
| item | result |
|---|---|
| LUT-INIT cells, 16 LEs x 16 bits x 4 LABs (X10Y10, X58Y30, X37Y60, X100Y75) | 1024 / 1024 pairs = exactly 1 cell |
| clock-polarity cell (clk vs ~clk) at the 4 LABs | 4 / 4 single cells, all tile-relative (df -6, dv -30) |
| distinct single cells now isolated | 1028 = 4 x (256 INIT + 1 clock polarity) |
| INIT cell SET per LE vs X10Y10 | identical in 48 / 48 (LE, LAB) combinations |
| INIT bit -> cell labelling vs X10Y10 | 15 of 16 LEs share one permutation per LAB; LE 0 differs |
| connect a second sink port (unconnected -> LL I, port p) | 2 cells in 112 / 112 pairs |
| adaptive splitting, budget 300, depth 1 | 0 new distinct cells; depth 2 had no candidates |

- Translation law: the FX/vy translation is exact for the cell SET. The 9 "shifted" sink-INIT cells of round 1 are bit-label permutations, not position shifts.
  - Permutations: X58Y30 and X37Y60 (0,8,2,10,4,12,6,14,1,9,...); X100Y75 swaps bit groups 4-7 and 8-11.
  - Likely cause: all LUT ports are tied to the same net (`ina`), so the fitter may permute ports and rewrites the mask. Not yet proven; test = a design with a distinct net per port.
- Use cell positions (not bit labels) when comparing LABs.
- Second sink on the same LOCAL_LINE: connecting costs 2 cells, one depending on the local line (df -11..-17), one on the port (D: df -9, C: df -10), row set by the sink LE.
  - Not split further: no unconnected -> 1-cell state exists for a port; other legal ports are re-routed by the fitter (B refused for the second sink).
  - A dangling sink with no fan-out is swept by the fitter (also the earlier `lab_modes` fan group, 0/45 honoured): the second sink must drive a pin.
- 448 second-sink variants honoured=False came from that sweep; rerun with the pin-driven sink: 336 ok, 112 refused (fitter picked another port).
- Bare grid (unused ports unconnected, 480 variants): source move 6-8 cells, port change 4, sink move 10+; no distance-1 pair.
