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

## Tripwires — stop and review the premise when any fires

- A report asks for "more corpus coverage" — the signature of a statistical dead end.
- A stopping rule fires. The response is a premise review, not the next same-level workaround.
- The gate is flat across two attempts at the same level.
- An approach scores worse than a strictly weaker one — measurement bug until proven otherwise
  (the #136/#138 alias-scoring failure).
- Any table is being learnt from more than ~10 designs — you are doing statistics; go to Phase 0.

## Case study: Cyclone IV (#141)

- The method was documented in four places before the deviation (#108, CLAUDE.md device-db rule,
  the MachXO2 precedent, docs/cycloneiv-ddb-format.md) — documentation was not the gap.
- Failures: no Phase-0 decision (both routes started the same day, attention followed the fast
  numbers); the blocking fan-out decode was parked in a doc sentence, not an issue; the ceiling
  math was never done; the stopping rule compared relatives, never the absolute requirement;
  tasks were framed as "improve recovery"; three "needs more coverage" tells were ignored.
- Outcome: four statistical stand-ins (#117 learner, #136 alias scoring, #139 intersection,
  #140 positional voting), gate pinned at ~4% for days against a 99.9% per-hop requirement.
