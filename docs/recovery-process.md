# Family recovery process

How pluribus recovers a new FPGA family. Written after the Cyclone IV methodology failure
(#141, 2026-10-28): the statistical routing detour cost ~5 days against a method that was
already documented. This doc makes the method binding, not advisory.

## Principle: brute force first

- The die is finite and the host is big (limits: `scripts/heavy_guard.py` constants, `docs/memory-budget.md`): enumerate, don't infer. Specimen
  sweeps, offset searches, candidate pairings — run them exhaustively in parallel; the recovery
  is CPU+RAM work and should be quick.
- Pattern generalisation (tile classes, mirrors, strides) is an optimisation only. Every
  generalised answer verifies against brute-force ground truth; on ANY mismatch, bail and
  enumerate that region outright. A pattern that fails verification never degrades to "mostly
  holds" — it reverts to enumeration.

## How the code is built (binding; Dan, 2026-10-29)

Applies to every phase below: lifters, decoders, specimen solvers, gates, inventories.
- **Free-threaded Python (NoGIL, python3.15t), proven here.** `sys._is_gil_enabled()` stays `False` across the stack; the whole pipeline is one interpreter.
- **Threads everywhere.** Parallelism = threads (`ThreadPoolExecutor`, `build_pool.map_adaptive`), never `multiprocessing`/`ProcessPoolExecutor`. External EDA tools (Quartus, Diamond, yosys) are the only subprocesses. Per-device read-only data is built once and shared by all threads (8 concurrent ECP5 85F lifts = ~2 GB, #148).
- **Efficiency over stability.** A bug in one thread can crash the whole run; accepted. Stall timeouts and memory leases bound the damage; every run rebuilds from scratch anyway.
- **numpy is the numeric core and is already highly optimised.** Bit planes, group decode, graph walks and set operations are vectorised numpy over dense arrays (the die is finite: 39.4 M cells, 14.9 M routing edges, all in memory or `mmap`'d). Measured against Rust and SQL (#144, `docs/rust-candidates.md`): nothing earns a Rust rewrite; vendor tools dominate every gate's wall time.
- **When something is slow:** better algorithm, then numpy vectorisation (dense bitmap + gather, sort + diff, dtype downcast), then threads over independent items, then an SQL index. Rust only for a measured >= 5-10x on a stage that dominates a pipeline.
- **Memory is the limit, not CPU.** Every heavy job holds a memory lease (`docs/memory-budget.md`); peaks are measured (`scripts/mem_report.py`), not guessed. Read-only tables are `mmap`'d numpy arrays or one shared in-process object.
- Why this matters for recovery: brute force over the whole die is only cheap because of this stack (dense arrays, shared tables, threads); a pattern that needs per-process copies or Python object graphs per design is the wrong design.

## Phase 0 — data-source decision (before any recovery code)

- Enumerate the sources, in order of strength:
  1. **Vendor device DB on disk** (Quartus .ddb, Diamond/Trellis DB, Gowin chipdb) — exact, complete
  2. **Minimal-diff specimens** — 1–2 cells, one net, one feature per diff; vendor tool pins placement/routing; diff or single-path readback gives exact answers; tile regularity generalises
  3. **Open projects** — prjtrellis, mistral, apicula, X-Ray: both a source and a format Rosetta
- **Exact labels or nothing.** A table entry is derived only from builds whose vendor output names the feature (RCF path, post-fit `.vo` parameter, MIF), by **pair diff**: two builds differing in ONE named feature. Every supporting build id is recorded; ONE contradicting build voids the entry (zero tolerance, never a vote). Must-be-clear cells are part of the entry.
- **Banned as a decode path:** majority or weighted voting, agreement thresholds below 100 %, learnt or fitted maps as a source, labels produced by our own decoder (alias matching), entries without build ids. No learned-table scorer or comparator is kept in the repo (the Cyclone IV learner baseline was deleted 2026-10-29: it outscored the exact path on pins and invited its use). The change-detector allowance covers real-design LUT/FF/net counts only.
- **Where statistics IS fine (not a table source):**
  - **Triage:** frequency of set bits across images/corpus to rank which unknown regions matter.
  - **Hypotheses:** a fitted pattern (e.g. an address law) is a prediction; a specimen then verifies it.
  - **Outlier flags:** disagreements between sources point at a bug to investigate.
  - **Measurement:** coverage %, per-hop accuracy, held-out hit rates.
  - **Last-resort fallback** where no exact route exists yet: allowed only as its own tier
    ("statistical, unverified") shown separately in the inventory, and replaced as soon as an exact
    source covers it. Never mixed into verified counts.
- Write the decision in a numbered issue per table (cells, routing, clocks, IO): which source,
  why, and the fallback. An approximation proposal must include the ceiling math (below).
- Precedent: every successful family followed this. MachXO2/ECP5 = vendored DB + small fuzz
  corpus. Mistral (Cyclone V) = decoded Quartus's own tables. Nobody upstream learnt routing
  statistically.

## Phase 1 — oracle + gate before tables

- Corpus = vendor builds with full back-annotation (post-fit netlist + routing report).
  **Verification only** — never a table source.
- **Vendor-tool outputs are kept, never regenerated** (Dan, Bluebird rule, restated 2026-10-28):
  every build lives under `corpus/<family>/<name>/` with its outputs; `design.toml` records the
  generator inputs AND the provenance — vendor tool + version, build date. Sources + toml are
  git-tracked; bulky outputs stay on disk and are reused (solvers cache against them). A build is
  redone only when the tool version changes deliberately, and then as a new provenance entry.
  The queryable index is the `corpus_builds` table (`schema.py`), rebuilt by
  `scripts/corpus_register.py --family <f>` (full rescan — derived index, rebuild is the
  migration); run it after every build batch. Check the DB before regenerating anything.
- **Bookkeeping is enforced by code, not memory:** `evidence_io.record_specimen` rejects a specimen-pair row without `build_base`/`build_spec`; `build_pool` stores refused/failed outcomes via `on_outcome` (`record_build_outcome`) but does NOT run `corpus_register` (run it after every batch, above); a gate exits 4 if `record_gate_run` was not called (`corpus.gate_exit_code`: enforced in `machxo2_gate.py` and the Cyclone IV tracer `cycloneiv_ddb_trace.py` only; ECP5 and Gowin gates do not record to `gate_runs` yet, #159); refused/failed builds are stored with a status (no silent loss).
- Declare ONE fixed gate set in the issue; every number ever reported cites it. A changed set is
  a new baseline, stated as such.
- Headline per the scoring-faults rules: matched / (matched + missing + extra + wrong). Missing
  is a fault equal to wrong.
- **Per-hop accuracy by wire class ships with the first scorer.** The net/sim gate is a
  cone-product: matched ≈ (per-hop)^(cone size), so it cannot move until per-hop is ~99.9%, and
  it cannot steer work. Both metrics, always.

## Phase 2 — exact table recovery

- Primary: decode the vendor DB (mistral pattern).
- Validator: minimal specimens (prjtrellis pattern). The two must agree wherever they overlap.
- **A parked sub-decode gets a numbered issue at the moment it is parked**, with the evidence and
  what was tried — never only a doc sentence or commit message. The issue queue is what drives
  the work; a gap that isn't an issue does not exist to the next session.
- Agent task framing names the source: "decode X from Y", never "improve recovery of X".

## Phase 3 — lift + gate

- One deterministic lookup path. No fallback piles; while any hybrid exists, every answered hop
  records which source answered (bisectable).
- With exact tables, **wrong must be 0**. Any wrong point is a decode bug, not noise.
- Count faulty cones (root causes) beside faulty points: one wrong input poisons a whole carry
  chain and inflates point counts.
- **A decode rule (firing, select, coordinate map) changes only on a specimen that shows the new prediction.** Gate-only tests of decoder variants are banned. When a rule changes, entries made under the old rule are re-tiered or deleted in the same commit.

## Done criterion — the corpus is the acceptance test (Dan, 2026-10-29)

- Per family, ONE declared corpus (`corpus_members`, `required = 1`) and one gate script. The gate
  writes every run into `gate_runs` / `gate_results` (`provenance.corpus.record_gate_run`) with
  matched / missing / extra / wrong per category; headline = matched / (matched + missing +
  extra + wrong) (scoring-faults rules: missing and extra are faults).
- **Done = every required member at headline 100 % in every category with wrong = 0** in the latest
  run. Then `done_criteria.state = met`; every open `unknowns` / `expectations` row of the family
  is classified `not-required-by-corpus` and parked — never deleted, still queryable, still
  distinguishable (unknown with no hypothesis vs expected-by pattern/matcher).
- A later failing run re-opens EXACTLY the items its failing cone rests on: `gate_results.failing_claims`
  (from `lift_provenance.claim_ids` of the mismatching objects) → those claims `suspect`, their
  patterns `suspect` (siblings too), parked unknowns / expectations on those scopes `open`, audits
  queued with reason `corpus-fail`; `done_criteria.state = open`.
- Nothing more needs solving once the corpus passes; the parked queue is what a widened corpus
  would re-open. Status: `scripts/framework_status.py` (per family, per database).
- Today: ECP5 corpus = the 240 Diamond-oracle targets of `tests/baselines/ecp5_oracle.json`;
  MachXO2 = the four `machxo2_gate.py` sets; Gowin = `gowin_lec.py` designs; Cyclone V =
  `corpus_builds` ok rows; Cyclone IV = the 76 required `gx150_rb` members (af73c732b).

## Tripwires — stop and review the premise when any fires

- A report asks for "more corpus coverage" — the signature of a statistical dead end.
- A stopping rule fires. The response is a premise review, not the next same-level workaround.
- The gate is flat across two attempts at the same level.
- An approach scores worse than a strictly weaker one — measurement bug until proven otherwise
  (the #136/#138 alias-scoring failure).
- A table entry whose supporting set tolerated a contradiction, or whose label is not a vendor output, is statistics; go to Phase 0.

## Specimen rules for agents (binding; Dan, 2026-10-28)

The method is the prjtrellis/X-Ray one. Do exactly this, nothing bigger.

- **Specimen = base build + specimen build, differing in ONE thing.** Answer = raw config-bit
  difference between the two. No decoder (`Dec.active`, asm firing, learnt maps) in the loop.
- **Smallest first.** Tier 0: one hand-placed LUT, one net (output fed to its own input), base has
  the input unconnected. Tier 1: two LUTs, same LAB, one net. Only then scale.
- **Same cells, same placement, same lut_mask in base and specimen** — the diff is routing only.
- **Split multi-mux diffs by diff-of-diffs:** vary ONLY the input, or ONLY the source position.
  Prefer forcing one pip via RCF input where it works.
- **Report before scaling.** After Tier 0/1 report: bits flipped, muxes on the RCF path, rebuild
  gives identical bits (y/n). Do not start a sweep until that is reported and checked.
- **Do not get clever.** No new decoders, no statistics/voting, no pattern inference as a source,
  no tooling beyond gen/build/diff/store. A pattern is allowed only as a prediction that a
  brute-force specimen then verifies; on any miss, enumerate.
- **Do not widen scope.** Do not retire code, rewire the lifter, or change the gate (#142 is a
  separate, gated step). **One feature per DIFF.** A pair changes one thing. Progress is counted in answered features, never builds.
- **Stop and report** if the method cannot be applied (e.g. forcing impossible, diff unstable).
  Never slide back to decoder matching to keep going.
- **Every agent brief states:** (1) the question as "decode X from Y"; (2) the prediction and what refutes it; (3) the oracle; (4) the build cap and yield floor ("Yield rule"); (5) the stop criterion and what is reported at stop; (6) the issue that owns the gap; (7) the ledger row that will show the result. A brief missing an item is returned.
- Every report states yield vs floor, issues filed, and rules it could not follow. Briefs quote this section; they do not paraphrase it.

### Specimen design (every family; Dan, 2026-10-29)

- Applies to any bitstream: the vendor tool differs per family, the design rules do not. A method that
  works on one family and not another is a tooling gap to record, not a reason to change the rules.
- **Object = smallest that holds the feature:** one LE in an otherwise empty LAB, one pin, one port. No
  functional designs, no far FFs, no extra routed nets.
- **One knob per pair:** present/absent (enable, clear), polarity (active-high/low via one inverter),
  position, constant tie. Nothing else differs.
- **Same routing in both builds:** feed the base's post-fit routing back as a constraint (RCF
  back-annotation or the family's equivalent) so the router uses the same area; only the new thing
  routes freely.
- **Control nets come from the same LAB/tile** and exist in both builds.
- **Null controls first:** same design renamed. The diff must be empty; if not, nothing else is trusted. A seed change is a null only under back-annotated routing; otherwise its diff is recorded as the placement/routing noise floor.
- **A noisy diff means the object was too big:** shrink it (diffs mixing routing bits of the added
  connection with the feature bits, as in the first control-line sets) rather than add statistics.

### Priority order (binding; Dan, 2026-10-29)

- **Rank by what gates the lift.** The queue is the latest gate run's per-hop table by wire class, largest missing + wrong first. The Done criterion (corpus gate) is the target. Die coverage % (`scripts/cycloneiv_bit_inventory.py`) is reported, and ranks only classes the gate does not touch.
- **A metric change is a new baseline,** stated as such; it never replaces the gate in the headline.
- Within a gate-neutral class: unknown bits converted per specimen, big regular blocks first (M9K = 36 % of the die), small/irregular last.
- **Easy and large before hard and small.** Edges, corners and one-off pin cases come AFTER the
  interior class they truncate is fully known: an edge is a deviation from the interior pattern,
  so the pattern must exist first.
- **Work a block's checklist easiest-box-first** (docs/cycloneiv-specimens.md "Block checklists"):
  each ticked box adds to die coverage on its own, so partial progress counts.
- **A stuck box does not block the queue.** Two failed attempts → park it as a numbered issue
  with the evidence, move to the next box or block; the inventory keeps it visible.
- **Elimination is a tool, not a gate.** When a block's remaining unknown set bits are few, name
  them and attack them by elimination; do not hold other blocks back to reach that point.
- Re-rank after every gate run: the gate per-hop table is the queue; the inventory unknown-regions table ranks only gate-neutral classes.

## Single-bit confirmation (Dan, 2026-10-29)

Pairs prove a bit SET; the aim is to state what each single cell does. Evidence levels, weakest first (recorded on the evidence row, never mixed in one count):
1. **Set**: base + specimen differ by one design change; the diff is a set of cells (typically 3-6 for a routing choice).
2. **Attributed** (the acceptance level for routing, control and mode bits): feature f has a full pattern P(f) over a footprint F (set and must-be-clear cells); every cell of F is tied to f or to one named variable by a grid in which each variable is varied alone (>= 2 values each, other variables fixed); rebuild-stable. A 2-5 cell group is a complete answer. `scripts/cycloneiv_localline_bits.py` is the model.
3. **Isolated (strict single cell; required only for cells claimed to be single-bit flags)**: two vendor builds of the same design that differ by one small design change and by EXACTLY ONE cell. The alternate bitstream is always a vendor build of a slightly different design, never a hand-edited file.
4. **Hardware-confirmed**: the isolated cell flipped on real silicon changes the predicted behaviour (needs a board; decision #156).
- **Bit hunter** (`scripts/cycloneiv_bit_hunter.py`): automated search for level-3 pairs. Calibration pairs are not results; a knob that gives no distance-1 pair in 20 variants is closed at level 2 and not re-run; re-measuring a verified/measured cell counts 0 in every ledger. One pinned base design, hundreds of variants that each change exactly one knob (a LUT-mask bit, source/sink LE, port via a forced route, FF on/off, tied constant, control line), all pairs compared at full-plane level, pairs at distance 1 recorded (`n_objects = 1`), pairs at distance 2-3 split by in-between variants. It will not always find one; a hit is exact. Calibration first: one LUT-mask bit must flip exactly one cell (verified INIT cells), else the harness is wrong.
- Confounded cells (identical membership over every pair so far) are listed as a queue of minimal specimens, not guessed.
- A role is written for a cell only at level 2 or 3; a level-1 set never becomes a per-cell claim.

## Yield rule (stop and continue; Dan, 2026-10-29)

- Before launch every sweep states: the question ("decode X from Y"), the predicted diff (cells, +/-, must-be-clear), a build cap and a yield floor.
- **Yield = distinct new meaning-bearing cells or answered features per 100 builds,** computed by `scripts/progress_ledger.py` from evidence rows new since the last ledger row; the row prints yield vs floor. Defaults: routing 10 features per 100 builds, isolation hunts 1 new cell per 100.
- **Stop on:** yield below the floor over the last 200 builds, or the cap. Stop = report + numbered issue, not another round.
- **On a prediction miss:** enumerate that scope (every row of the failing key) before anything else; do not fit a replacement rule from the misses, and do not launch another one-hypothesis round.
- A gate flat (< 0.5 pp) across two attempts at one level stops that level.

## Patterns and certainty (Dan, 2026-10-29)

- **Every detected pattern is reported.** A rule found by inspection or fitting goes into the report and the DB as a `pattern-predicted` claim with its sample size and misses; it is never folded into measured counts.
- **Tier names are the Glossary in `docs/provenance-and-feedback.md`** (verified, measured, sampled, pattern-predicted, decoded, statistical, suspect, refuted, unknown; "projected unused" is a triage sub-line of unknown, not a tier). Nothing here redefines them.
- **The DB tags certainty per claim**, on a cell, a range or a class (`claims.tier`, `status`, `confirmations`, `refutations`, `scope_id`; statuses in `docs/provenance-and-feedback.md`). Reports and the coverage page group bits by these tags, never by one "evidence" bucket.
- **Patterns are never locked.** A missed corner case flips the claim to `suspect` or `refuted` and the bits fall back to `predicted`/`unknown`. A pattern is preferred to enumeration only until a specimen contradicts it; on any miss, enumerate that scope.
- **Coverage counts a pattern that has confirmations at >= N distinct scopes (extremes included) and zero refutations** (`sampled` = verified-by-sampling; N and the rule: `provenance/tiering.py`). It is shown as its own line beneath the headline ('rule verified by sampling (not exact per cell)'), never merged into it; the headline is verified + measured only (#157 decision 4).
- **A real lift or reverse build that fails makes every pattern claim in its path suspect** until the failure is explained, whatever its coverage status. The gate decides; coverage only reports.
- **Sampling plan for a grid or array of like tiles** (LAB array, M9K columns, IO ring):
  - Test the **four corners** of the region plus a **sample from the centre** (seeded, ~10 %, at least 3 tiles).
  - Corners and edges are their own class: never pooled with the interior; a rule extends to an edge only if an edge specimen agrees. The edge sample is the corners plus a few points along each side, not every edge tile.
  - If the grid is broken into areas (different tile types, column kinds, row bands, hard-IP islands), apply the same plan **per area**: its four corners + a centre sample.
  - All sampled tiles agree -> the rule is `verified-by-sampling` for that area, with n and misses on the row. One miss -> enumerate that area (not the whole die).
  - Record the sample plan (which tiles, seed) with the claim so it can be re-run.
- Not required: testing every site/cell. A rule that passed the sampling standard stands; stated sample size and miss count are the evidence.

## Case study: Cyclone IV (#141)

- The method was documented in four places before the deviation (#108, CLAUDE.md device-db rule,
  the MachXO2 precedent, docs/cycloneiv-ddb-format.md) — documentation was not the gap.
- Failures: no Phase-0 decision (both routes started the same day, attention followed the fast
  numbers); the blocking fan-out decode was parked in a doc sentence, not an issue; the ceiling
  math was never done; the stopping rule compared relatives, never the absolute requirement;
  tasks were framed as "improve recovery"; three "needs more coverage" tells were ignored.
- Outcome: four statistical stand-ins (#117 learner, #136 alias scoring, #139 intersection,
  #140 positional voting), gate pinned at ~4% for days against a 99.9% per-hop requirement.
