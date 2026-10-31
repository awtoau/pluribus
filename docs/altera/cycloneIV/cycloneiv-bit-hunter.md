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
- Null controls run first and gate the batch: renamed design (empty diff); other seed only under back-annotated routing, else its diff is the noise floor (0 cells, 5 pairs, back-annotated).
  - First attempt failed: free-fit base vs back-annotated base differ by 2 cells; fixed by the `boot` build. The pair stays in the table.
- Evidence: `record` writes one row per (cell, knob) as `bit_hunter:<knob>` (spec = plane i, base = plane j, n_objects 1); meta has frame, v, tile, (df, dv).

## Rerun
```
python3.15t scripts/cycloneiv_bit_hunter.py batch1 --jobs 22   # nulls, then all knobs
python3.15t scripts/cycloneiv_bit_hunter.py batch2|batch3 --jobs 22
python3.15t scripts/cycloneiv_bit_hunter.py adapt --budget 100 --depth 3
python3.15t scripts/cycloneiv_bit_hunter.py replicate           # distance-1 pairs rebuilt at X58Y30
python3.15t scripts/cycloneiv_bit_hunter.py round2a|round2b|round3|round4 --jobs 22   # INIT/clock pairs; LL + 2nd sink; control + LAB variants; clock/DN pairs at extra LABs
python3.15t scripts/cycloneiv_bit_hunter.py law|analyse3        # INIT cell position law vs X10Y10; round-3/4 analysis (no builds)
python3.15t scripts/cycloneiv_bit_hunter.py report|record       # summary.json / evidence rows
```

## Results (2026-10-29, 851 builds ok, 8 refused by the fitter)
| item | result |
|---|---|
| calibration: sink LUT-mask bit | 16 / 16 variants = exactly 1 cell |
| calibration: source LUT-mask bit | 16 / 16 variants = exactly 1 cell |
| calibration: clock polarity (`clk` / `~clk`) | 1 cell (known class 1c; counts 0 features in the ledger) |
| new single cells at X10Y10 | 0; the 33 distance-1 pairs = 32 LUT-INIT + 1 clock-polarity, all calibration of known cells |
| calibration replicated at X58Y30 (same pairs rebuilt) | 24 / 33 land on the same (df, dv); 9 sink-INIT cells shift by (+-1..3) in (df, dv) |
| refused by fitter | FF power_up=high (needs an inverter in the same LE), 3 sload variants |
| unreachable here | any control-net connection (ena, aclr, sclr, clk source): 20-100 cells each |

Calibration (known cell, not a new result): `clk` vs `~clk` (same source LE, FF clocked directly or inverted) flips exactly one
cell, tile-relative (df -6, dv -30) = the LAB clock-polarity cell (inventory class 1c). Holds for source KA and KB.

Hit rate per knob (exactly 1 cell vs base): LUT mask (sink) 16/48 (the rest are multi-bit masks), LUT mask (source) 16/16,
clock polarity 2/2; all others 0 (src LE 0/8, snk LE 0/14, port 0/1, tie 0/6, ff 0/1, ena/aclr/sclr/clk-source 0/50).

## Named pairs, diff cell count (one-LE LAB, same back-annotated routing)
| pair | cells |
|---|---|
| null: renamed, other seed (back-annotated) | 0 |
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

## Round 3 (2026-10-29)
### 1. Distinct net per LUT port (INIT bit labels)
- Design `dn`: u0 and u1 ports tied to four different input pins (u1 keeps u0's net on the forced port). Same LE x bit enumeration as round 2 on LEs 0, 1, 2, 8, 15.
- Result vs X10Y10 (bit label -> cell, tile-relative): LEs 1, 2, 8, 15 (sink role) 64 / 64 bits identical at each of the 3 other LABs. LE 0 (source role, four free pins) still permuted (2-4 / 16 identical).
- Cell sets identical in 5 / 5 LEs at every LAB.
- Conclusion: the label shifts of round 2 come from the fitter swapping ports that carry the same net.
- Rule for specimens: give every LUT port a distinct net, or compare cell sets / positions only (round 4 uses cell sets).

### 2. Control nets driven from a pin (X10Y10, X58Y30)
- Base: FF in the test LE, clock from a same-LAB LUT, pins `enap`, `clrp`, `sclp` already feed test-LUT ports B/C/D (so the pins and their routes exist in base); control ports unconnected. Spec connects ONE pin to ONE control port. Base routing back-annotated.
- Cells added by connecting `enap`: ena 4, aclr 5, sclr 5 (X10Y10); 3, 4, 4 (X58Y30). Other pins 11-16.
- Control-port cells by subtraction (intersection over the three pins; identical at both LABs):

| port | cells (df, dv) |
|---|---|
| ena | (-8, -30), (-7, -30) |
| aclr | (-1, -32), (0, -32), (3, -68) |
| sclr | (2, -32), (4, -1) |

- The rest of each set is the pin's route into the LAB (one cell cleared, one set at X10Y10): ena/enap = port cells + (-19, -35) cleared + (-10, -35) set.
- No single-cell state: a control port connects as a 2-3 cell group. sload (+ asdata) is refused by the fitter in all 3 variants per LAB.
- The ena and aclr groups sit in the rows next to the clock-polarity cell (-6, -30).

### 3. LOCAL_LINE second sink: 2-cell sets per LAB
- Pin-driven second sink, unconnected vs connected, at X10Y10 plus X58Y30, X37Y60, X100Y75 (sink rows k2 = 2 and 16): 42 role tables, 157 (LAB, row, port, line) entries; each LAB's table equals X10Y10's in 12 / 12 comparisons.
- Port C (lines 2, 4): fixed port cell (-10, row-1) plus a line cell ((-17, row) line 2, (-16, row-1) line 4).
- Port D (lines 0, 6, 8, 10, 12, 14): the two cells are (-15..-11 .. -13, row) and (-9, row-1 or row); which of the two rows each takes depends on the line, so port and line cells are not separable into one fixed port cell. The df -9 column belongs to port D, the df -11..-15 column to the line.
- Tables: `tmp/bit_hunter/round3.json` (`ll`).

## Round 4 (2026-10-29)
- Distinct-net INIT enumeration for ALL 16 LEs (16 bits each) at 6 LABs: X10Y10 (reference), X58Y30, X37Y60, X100Y75 and the corners X1Y1, X116Y90.
- Cell sets identical to X10Y10 in 16 / 16 LEs at each of the 5 other LABs (position comparison; bit labels identical 242-244 / 256 at the 4 inner/far LABs, 122 / 256 at X1Y1; LE 0 is the free-pin source LE).
- Clock polarity (clk vs ~clk) is a single cell at all 6 LABs, tile-relative (df -6, dv -30).
- Claim 1c: tier is computed (`provenance/tiering.py` class_verdict) from the bit-hunter rows linked in `claims_register.py`: 6 distinct scopes >= 5 for a 2-D law, axis extremes (x 1 and 116, y 1 and 90) included, 0 refutations -> sampled.
  - Round 3 hand-set the status at 4 LABs; reverted. At 4 LABs the function returns predicted (below the bar and extremes missing).
