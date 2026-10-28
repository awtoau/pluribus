# Cyclone IV GX150 LOCAL_LINE pips from specimens

Tool: `scripts/cycloneiv_pip_table.py` (`table` / `validate` / `image`); tracer option `cycloneiv_lift_image.py --ddb --localline full|pq`.
Evidence: 4 same-LAB LOCAL_LINE grids (X10Y10, X58Y30, X37Y60, X100Y75), evidence rows kind `specimen-pair` (`cycloneiv_forced.py`). Method: [recovery-process.md](recovery-process.md).

## Table

- 240 pairs (16 source LE x 15 sink LE, no self), 4 tile-relative cells each; 305 distinct cells.
- Key = (source LE index i = N/2 = RCF `LOCAL_LINE:...I<i>`, sink LCCOMB N, physical port). Port is fixed per pair in the specimens (DATAD 150, DATAC 90); DATAA/DATAB never observed.
- Translation: cell = (FX[x] + df) * 6368 + (vy0 + 70 y + dv). All four LABs agree on all 240 pairs (0 dropped).
- Bit roles: 2 source-LE cells (C = df -8, D = df +2; set for every pair of one source), Q = sink+port, P = pair.
- Resolver: all cells of a pip set = present. Output is the candidate set per sink input (LAB, sink N, port); one candidate = unique. No candidate is chosen among several.

## Validation (76 gate designs `gx150_rb*` odd split, all have `routing.rcf` + `bitstream.rbf`; 2026-10-29)

- Truth = RCF `LOCAL_LINE -> sink` hops whose sink is an LCCOMB in the same LAB: 41,842 sink inputs.
- Counts per sink input; headline = matched / (matched + missing + extra + wrong).

| mode | bits used | all 41,842 hops | hops with a table entry (26,495) |
|---|---|---|---|
| full | 4 (specimen fact) | 24,232 / (24,232 + 17,610 + 1 + 0) = 57.91% | 24,232 / (24,232 + 2,263 + 1 + 0) = 91.45% |
| pq | 2 (P, Q; source cells ignored) | 26,458 / (26,458 + 15,384 + 1 + 0) = 63.23% | 26,458 / (26,458 + 37 + 1 + 0) = 99.86% |

- wrong = 0 and ambiguous sink inputs = 0 in both modes (no shared-bit aliasing seen in these designs).
- Misses, causes:
  - 15,346 sink port DATAA / DATAB: not in the specimens (one-port-changed grid still to build); 1 self-source (source LE = sink LE).
  - full only, 2,226: source-cell C absent when the source LCCOMB is in arithmetic mode (`sum_lutc_input=cin`; 143 of 143 in a 25-design sample), D absent when the source LE is registered (FF at N+1; 538 of 539), both absent for FF-only (5). These are source state, not the pip: the specimen sources were plain comb LEs. `pq` mode ignores both cells; the rule is RCF-validated, not specimen-proven.
  - 37 residual in both modes: all at sink N10 in LAB row y34 or sink N30 in row y12 (P bit absent; row-specific offset not covered by the 4 specimen LABs).
- 1 extra (both modes): a unique candidate at a sink with no RCF LOCAL_LINE hop (cells shared with another pip class).

## The third-party EP4CGX150 image (2026-10-29)

- Resolver alone: `full` 19,240 sink inputs resolve to one pip (0 ambiguous; 3,658 of 9,360 LABs); `pq` 32,533 (0 ambiguous; 5,094 LABs).
- Lifter with `--ddb --localline <mode>` (specimen answer first when unique, else the ddb tracer; tag `specimen-localline`; default path unchanged), LCCOMB pins:

| run | agree with ddb tracer | gain (ddb unresolved) | differ | unique, source cell unreadable | unresolved LUT inputs (mask-dependent) |
|---|---|---|---|---|---|
| ddb only | - | - | - | - | 234,653 |
| full | 17,144 | 2,067 | 2 | 22 | 232,714 |
| pq | 28,176 | 3,529 | 6 | 635 | 232,599 |

- Fixed 76-design validation says wrong = 0 for both modes; the 2 / 6 `differ` pins are unadjudicated (no RCF for the image).
- Coverage is bounded by ports: DATAA/DATAB hops (37% of RCF LOCAL_LINE hops) are unresolved until their specimen grid exists.
