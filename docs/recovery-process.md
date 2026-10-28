# Family recovery process

How pluribus recovers a new FPGA family. Written after the Cyclone IV methodology failure
(#141, 2026-10-28): the statistical routing detour cost ~5 days against a method that was
already documented. This doc makes the method binding, not advisory.

## Principle: brute force first

- The die is finite and the host is big (32 cores, 64 GB): enumerate, don't infer. Specimen
  sweeps, offset searches, candidate pairings — run them exhaustively in parallel; the recovery
  is CPU+RAM work and should be quick.
- Pattern generalisation (tile classes, mirrors, strides) is an optimisation only. Every
  generalised answer verifies against brute-force ground truth; on ANY mismatch, bail and
  enumerate that region outright. A pattern that fails verification never degrades to "mostly
  holds" — it reverts to enumeration.

## Phase 0 — data-source decision (before any recovery code)

- Enumerate the sources, in order of strength:
  1. **Vendor device DB on disk** (Quartus .ddb, Diamond/Trellis DB, Gowin chipdb) — exact, complete
  2. **Minimal-diff specimens** — 1–2 cells, one net, one question per build; vendor tool pins placement/routing; diff or single-path readback gives exact answers; tile regularity generalises
  3. **Open projects** — prjtrellis, mistral, apicula, X-Ray: both a source and a format Rosetta
- **Statistics over random builds is not a source.** Pooled/voted/learnt tables are banned as a
  decode path. Allowed only as a change detector (like real-design LUT counts).
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
  The queryable index is the `postfit_builds` table (`schema.py`), rebuilt by
  `scripts/corpus_register.py --family <f>` (full rescan — derived index, rebuild is the
  migration); run it after every build batch. Check the DB before regenerating anything.
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
  `postfit_builds` ok rows; Cyclone IV = NO required member yet — the gate set must be declared
  before its done state means anything (`claims_register.py` logs this).

## Tripwires — stop and review the premise when any fires

- A report asks for "more corpus coverage" — the signature of a statistical dead end.
- A stopping rule fires. The response is a premise review, not the next same-level workaround.
- The gate is flat across two attempts at the same level.
- An approach scores worse than a strictly weaker one — measurement bug until proven otherwise
  (the #136/#138 alias-scoring failure).
- Any table is being learnt from more than ~10 designs — you are doing statistics; go to Phase 0.

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
  separate, gated step). One question per build.
- **Stop and report** if the method cannot be applied (e.g. forcing impossible, diff unstable).
  Never slide back to decoder matching to keep going.
- Agent briefs quote this section; they do not paraphrase it.

### Priority order (binding; Dan, 2026-10-29)

- **Target = die coverage %, not one image.** Metric: % of the die's configuration bits with a
  verified meaning (`scripts/cycloneiv_bit_inventory.py`). A single image only breaks ties.
- **Rank work by unknown bits converted per specimen.** Big, regular blocks first (M9K = 36 % of
  the die, uniform columns); small/irregular last.
- **Easy and large before hard and small.** Edges, corners and one-off pin cases come AFTER the
  interior class they truncate is fully known: an edge is a deviation from the interior pattern,
  so the pattern must exist first.
- **Work a block's checklist easiest-box-first** (docs/cycloneiv-specimens.md "Block checklists"):
  each ticked box adds to die coverage on its own, so partial progress counts.
- **A stuck box does not block the queue.** Two failed attempts → park it as a numbered issue
  with the evidence, move to the next box or block; the inventory keeps it visible.
- **Elimination is a tool, not a gate.** When a block's remaining unknown set bits are few, name
  them and attack them by elimination; do not hold other blocks back to reach that point.
- Re-rank after every inventory run; the doc's top-10 table is the queue.

## Case study: Cyclone IV (#141)

- The method was documented in four places before the deviation (#108, CLAUDE.md device-db rule,
  the MachXO2 precedent, docs/cycloneiv-ddb-format.md) — documentation was not the gap.
- Failures: no Phase-0 decision (both routes started the same day, attention followed the fast
  numbers); the blocking fan-out decode was parked in a doc sentence, not an issue; the ceiling
  math was never done; the stopping rule compared relatives, never the absolute requirement;
  tasks were framed as "improve recovery"; three "needs more coverage" tells were ignored.
- Outcome: four statistical stand-ins (#117 learner, #136 alias scoring, #139 intersection,
  #140 positional voting), gate pinned at ~4% for days against a 99.9% per-hop requirement.
