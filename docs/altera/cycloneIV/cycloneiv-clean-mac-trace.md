# MAC operand/sink trace and chain classification, DJI EP4CGX150 m2001 (#165, #177 item 4, #179)

Deterministic graph walk, not model-guessed: `lifters/cycloneiv_clean/functrace.py` (generic core, read-only
on the netlist) + `scripts/cycloneiv_clean_functrace_report.py --type mac` (CLI, MAC-specific plugin
inside the script). Image rebuilt fresh from HEAD (working tree had uncommitted M9K write-enable/TDP
fixes newer than the last `tmp/image_sim/nl.pkl`): `tmp/mac_trace/image_sim/nl.pkl`, built 2026-10-31,
58.6 s emit. 87 of 360 MAC instances used (unchanged from `docs/altera/cycloneIV/cycloneiv-clean-mac.md`).
Tags: **V** structurally confirmed by the trace, **I** inferred/heuristic, **U** unknown.

## 0. Re-verification of "33 of 87 take an M9K operand" (untracked prior finding)

- **Re-measured: 32 of 87** (not 33), independently cross-checked two ways:
  1. `functrace.trace_source` at `ff_hops=1` (one register stage of backward lookahead past each
     operand bit's own LUT cone) finds 32.
  2. `lifters/cycloneiv_clean/patterns.py`'s own `mac_rom()` detector (already in the codebase,
     unrelated to this task, built on `Design.support(sig, hops=1)`) independently finds **31**, a
     strict subset of functrace's 32 (one extra instance, `(14, 77)`, not chased further per the
     project's "don't chase the last cell" rule — both numbers round to the same finding).
  3. `ff_hops=0` (no register lookahead) gives 11; `ff_hops=2` gives 50 — over-attributes by reaching
     through a second register stage into unrelated accumulator feedback. `ff_hops=1` is the
     documented default in the report script for this reason.
- **Verdict: the "33" figure was close but not exact** — the real count on this build is 31-32 of 87
  (35.6-36.8%), not 33. Treat any future citation of "33 of 87" as superseded by this measurement.

## 1. Method

- `functrace.trace_source(design, sig, ff_hops)`: walks a signal backward through LUT cones
  (`patterns.Design.comb`/`.support`, reused not reimplemented) and up to `ff_hops` FF stages. Reports
  the single ultimate leaf kind (`const`/`pad`/`m9k`/`mac`) when the cone resolves to exactly one
  non-constant leaf, or `lab_logic` with the full leaf set AND which of those leaves are `m9k_`/`mac_`
  block outputs (`has_m9k`/`has_mac`) when the cone is mixed — the common real case: a word-select mux
  over several M9K read bits, address/select FFs, and the actual data bit, all in one cone.
- `functrace.trace_sinks`: the same walk forward via a precomputed fan-out index (every LUT pin, FF
  control, IO driver/oe, and hard-block operand pin that reads each signal).
- `functrace.chain_groups(nl, spec, ff_hops)`: for every used instance of one hard-block TYPE, traces
  every non-output pin; an edge is recorded `src -> dst` when the ultimate source (direct, or inside a
  mixed `lab_logic` cone) is another instance of the SAME type. Multiple operand bits hitting the same
  `(src, dst)` pair collapse to one edge (the earlier uncollapsed version inflated apparent fan-in/
  fan-out by operand width, a bug fixed before this doc's numbers were taken). Union-find over the
  edges gives connected components ("chain groups").
- Topology per group (`cycloneiv_clean_functrace_report.topology()`): plain structural description
  (linear chain / fan-in star / fan-out star / tree-branching / irregular) from in-degree/out-degree
  over the deduped edges — no forced signature label, per
  `docs/altera/cycloneIV/cycloneiv-image-prior-art.md`'s own "a correct topology description is more
  valuable than a forced FFT label."
- MAC-specific M9K content classification (coefficient-ROM vs data-buffer) is a plugin inside the
  report script (`mac_m9k_classify()`), not inside `functrace.py` — it reads the already-built
  `tmp/dji_m9k_content/classify.json` (per-tile content-shape stats from earlier M9K-content work) and
  applies a heuristic: `distinct_frac < 0.1` and `>= 8` nonzero words = coefficient-shaped (**I**),
  else data-buffer-shaped (**I**); tiles with no content entry (zero-filled at bitstream load,
  software-written at runtime) are `content_known=False`.

## 2. Chain groups (connected components of MAC<-MAC operand/output edges)

- **77 connected components total** over 87 instances: **6 multi-MAC groups** (16 instances) + **71
  isolated singletons** (no MAC<->MAC edge at all).
- Multi-MAC groups and their topology (V: edges structurally confirmed; topology label is **I**):
  | group (x,y) | size | edges | topology |
  |---|---|---|---|
  | (43,62),(74,62),(74,70),(74,71) | 4 | (74,70)->(43,62), (74,70)->(74,62), (74,70)->(74,71) | **fan-out star**: one MAC's output feeds 3 others as an operand -- shared-operand/broadcast shape, not a pipeline |
  | (103,49),(103,60),(103,68),(103,73) | 4 | (103,49)->(103,60), (103,49)->(103,68), (103,68)->(103,73) | **tree/branching**: one source feeds two, one of those feeds a third -- 2-level branch, not a flat fan-out |
  | (74,68),(74,69) | 2 | (74,68)->(74,69) | linear (2-link) -- accumulator/pipeline stage |
  | (103,5),(103,61) | 2 | (103,5)->(103,61) | linear (2-link) |
  | (103,66),(103,69) | 2 | (103,66)->(103,69) | linear (2-link) |
  | (103,71),(103,72) | 2 | (103,72)->(103,71), via **direct** (no fabric logic between: one MAC's `DSP_BUFFER` output drives another's operand pin with no LUT in between) | linear (2-link), tightest coupling of any pair found |
- **No group reaches the 12-20 MAC/stage count the prior-art doc names as an FFT-stage signature**
  (`docs/altera/cycloneIV/cycloneiv-image-prior-art.md` "identify an FFT... 12-20 MACs per FFT stage").
  The largest group is 4. **Negative for an FFT (or any filter structure needing >= 12 chained MACs)
  anywhere in this image's MAC fabric** (V, graph-exhaustive over all 87 used instances).
- Shapes found (fan-out star, 2-level tree, tight 2-MAC pairs) read as **small shared-operand or
  short-accumulator datapath**, not a recognisable DSP core signature. Consistent with the existing
  negative finding (`docs/altera/cycloneIV/cycloneiv-image-prior-art.md` section on Altera WiMAX/FFT
  MegaCore IP: "no cos/sin twiddle table and no FFT-shaped M9K set").

## 3. M9K-operand MACs: content classification (coefficient ROM vs data buffer)

- Of the 32 M9K-operand MACs, their operand bits' M9K tiles span **76 distinct (x,y) tile coordinates**
  across the 32 MACs (most MACs read several tiles across their 18-36 operand bits, consistent with a
  word-select mux per bit rather than one dedicated ROM per MAC).
- **Only 3 of those tiles have any decoded initial content** at all (`7_57`, `7_58`, `36_64` — 3 tiles,
  of which `7_57`/`36_64` are data-buffer-shaped and `7_58` is coefficient-shaped; the other 73 tile
  coordinates referenced by M9K-operand MACs have `content_known=False`): the vast majority of
  M9K-operand MACs read from tiles that are **zero at bitstream load** (`docs/lightbridge-fpga.md`
  section 8: "only 8 tiles hold data... None holds an FFT twiddle... feeding MAC inputs"). Those tiles
  are software-written at runtime (consistent with the existing TX-RAM finding in section 5 of the same
  doc: "both RAMs are zero at load, so software fills them").
- `7_58` (**I: coefficient-ROM-shaped**, `distinct_frac=0.008`, 4 distinct values over 512 nonzero
  words -- a small reused constant set) feeds MAC operand bits of **`(14,53)`** and **`(14,55)`**. This
  is the one MAC-plus-content-bearing-ROM pairing in the image with a classic small-coefficient
  signature (I, not matched to any specific known filter/FIR/twiddle table -- `cycloneiv-image-prior-art.md`
  already ruled out a twiddle-ROM shape for every populated tile by content, this only adds "and it
  happens to feed a MAC").
- `7_57` and `36_64` (**I: data-buffer-shaped**, `distinct_frac=1.0`, every word distinct) feed MAC
  operand bits of several MACs including `(14,53)` on its OTHER operand side -- i.e. `(14,53)` mixes a
  coefficient-like source on one side and a data-buffer-like source on the other, the shape a real
  multiply-by-coefficient against streaming data would have, though which operand carries data vs
  coefficient at runtime is not determined here (needs simulation with live data, out of scope).
- **No MAC reads an M9K tile matching a twiddle/NCO-sine/permutation signature** (already established
  independently by `docs/altera/cycloneIV/cycloneiv-image-prior-art.md` section 5 and the signature-cores
  comparison; this trace adds only which specific MACs touch the two content-bearing, MAC-feeding tiles).

## 4. Non-chained MACs (71 of 87): what they are instead

- Not traced individually to the same depth (out of this task's scope -- the prior session's scrambler/
  datapath work already classified the surrounding LAB logic via `patterns.py`'s counter/adder
  detectors; this trace's contribution is confirming these 71 have NO MAC<->MAC edge, i.e. each is an
  isolated multiply feeding/fed-by plain fabric logic, M9K, or a pad, not part of any filter/FFT chain).
- Output-sink kind counts across all 87 MACs' output bits (functrace forward walk, per bit, not
  deduplicated by instance): `m9k` 3,575, `ff_untraced` 6,501 (feeds a register beyond the 1-hop
  budget -- further pipeline stage, not traced deeper here), `mac` 1,272 (the chain edges above, counted
  per output bit before dedup), `dead_end` 796, `unused` 14. The largest single sink is `ff_untraced`
  (6,501); of the categorised sinks, M9K is the largest at 3,575 (a MAC product written back into block
  RAM). Read together: mostly isolated multiplies feeding a register stage or a RAM-backed buffer; the
  6,501 `ff_untraced` bits are unresolved beyond the 1-hop budget, so a deeper arithmetic pipeline is
  not ruled out here.

## 5. Cross-family generality: proof within Cyclone IV

- `scripts/cycloneiv_clean_functrace_report.py --type m9k` (same code, no changes) ran against the same
  netlist and produced the same report shape over all 542 modelled M9K instances in 19.7 s (263 chain
  groups, largest size 147) -- confirms the `--type` mechanism in `functrace.py`/the report script is
  genuinely generic over "any hard-block type with a `TypeSpec`," not hardcoded to MAC, WITHIN this one
  family's netlist shape. M9K chain semantics were not analysed (different task; M9K-M9K chains mix
  address-sharing and data-forwarding patterns that need their own classification, not reused here).
- Cross-family (ECP5/MachXO2/Gowin/Cyclone V) generality is explicitly OUT of scope for this change —
  see the separate scoping doc, `docs/functrace-cross-family-adapter.md` (awtoau/pluribus#180).

## 6. Side-check: open-source RTL tooling as an independent cross-check (per Dan's "never rely on one
source alone" ask, methodology doc principle 2) — attempted, inconclusive, not pursued further

- `yosys` 0.65+57 and `verilator` 5.046 are both installed on this machine.
- Tried: `yosys -q` with `read_verilog -sv` + `hierarchy -check` + `stat` against the freshly-built
  `tmp/mac_trace/image_sim/flat.v` (456,105 lines, one flat `cyc4_top` module, ~100 MB). Killed after
  6 min 47 s still inside the Verilog-frontend parse (had not reached `stat`), at 45 GB RSS on a 62 GB
  host with the machine already swapping (8.4 GB swap in use) — a real risk to the shared box, not a
  slow-but-finishing job. **Not retried**: a single 456K-line flat module (no hierarchy, no named
  sub-instances beyond `lc_`/`ff_` primitive cells) is a poor fit for yosys's frontend, which is built
  around hierarchical designs; `tmp/mac_trace/image_sim/rtl.v` (the hierarchical RTL-lift output,
  83 MB) might fare better but was not tried given the memory risk already observed on the flatter,
  smaller-looking file.
- **Verdict: no useful independent cross-check obtained from yosys/verilator analysis passes at this
  scale.** The MAC chain-detection result above rests on two independently-written graph walks inside
  this codebase (`functrace.py` and the pre-existing `patterns.mac_roms()`) agreeing to within one
  instance (section 0) — that is the cross-check this task actually has, not an external tool. No
  academic netlist-clustering or datapath-extraction tool was found or tried (none installed, and
  evaluating one from scratch was judged not worth it given the yosys result above); if a lighter-weight
  cross-check is wanted later, trying yosys against `rtl.v`'s per-module hierarchy (not the flat netlist)
  is the next thing to attempt, not re-trying the flat file.

## 7. Open / not chased

- The 1-instance discrepancy between `functrace`'s 32 and `patterns.mac_roms()`'s 31 M9K-operand count
  (`(14, 77)`) — not chased per the "don't chase the last cell" rule; both numbers support the same
  headline (31-32 of 87, not 33).
- Per-bit "which operand side carries the coefficient vs the live data" for `(14,53)`/`(14,55)` (the
  one coefficient-ROM-feeding pair) — would need simulation with live AD9363/demod data, out of scope
  here.
- 73 of 76 M9K tiles referenced by M9K-operand MAC bits have no decoded content (zero at load,
  runtime-written) — consistent with, not newly discovered by, the existing M9K-content work; not
  re-derived here.

## Pointers

- Code: `lifters/cycloneiv_clean/functrace.py` (generic walk/chain core), `scripts/cycloneiv_clean_functrace_report.py`
  (CLI + MAC-specific M9K-content plugin). Data: `tmp/functrace/mac.json`, `tmp/functrace/m9k.json` (both
  gitignored, local only).
- Prior docs this re-verifies/extends: `docs/lightbridge-fpga.md` section 8 (M9K content), `docs/altera/cycloneIV/cycloneiv-clean-mac.md`
  (MAC decode), `docs/altera/cycloneIV/cycloneiv-image-prior-art.md` (FFT-hunt recommendation, Altera WiMAX comparison), `docs/signature-cores.md`
  section 4 (known-core signatures). Cross-family scoping: `docs/functrace-cross-family-adapter.md` (awtoau/pluribus#180).
- Issue: #177 item 4 ("FFT-in-logic hunt") — this doc is that item's result (negative: no >= 12-MAC
  chain anywhere in the image).
