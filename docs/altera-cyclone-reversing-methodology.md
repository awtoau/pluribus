# Altera/Intel Cyclone-family bitstream RE: methodology from the Cyclone IV effort

Retrospective + forward plan. No new decode work; read-only on code. Derived from the Cyclone
IV GX (EP4CGX150, DJI m2001) effort in this repo. Every claim below cites the file/issue/ledger
row it comes from. Purpose: plan Cyclone V as ONE batch campaign, not the reactive loop IV ran.

Dan's framing (not softened): **the piecemeal "hit a block, spawn an agent, fix it, move on"
pattern was the project's one big mistake.** The fix is a systematic pass before the family's
decode work starts, not during it.

## 0. Standing principles (apply throughout every phase below)

1. **Find the writer code first.** A rule inferred from specimen diffing, however many builds
   agree, is never trusted as the origin of a decode rule — only the vendor writer function is.
   See section 2 for the ratio and the specific cases where this mattered.
2. **Inherited corpus/table data is a check, never a source of truth, no matter its age or how
   many times it has passed.** This applies to Mistral's data, Bluebird's imports, and — just as
   much — to this project's OWN existing e50f corpus, native tables and oracle results, however
   long they have stood unchallenged. A corpus entry, a passing gate, or a longstanding table value
   is evidence a rule is *consistent* with what's been tested, never evidence of *why* it is true.
   The exact failure mode already happened twice on Cyclone IV: the fitted coordinate model
   (E-C1/E-C2/E-C3) and the specimen-frequency routing-conduction rule (E-J1/E-L1/E-L2, section 2
   below) were both built on "this already works, trust it" reasoning — both were later shown to
   model the *wrong mechanism entirely* once the real writer code was read, not merely refined.
   Consequence for Cyclone V: before trusting any inherited or long-standing e50f corpus/oracle
   result as a foundation for a new rule, re-derive or re-validate it against a freshly code-read
   rule — CPU to regenerate a corpus is cheap; an inherited wrong assumption compounding through
   months of later work is not. This applies at the start of every Phase 2 (specimen generation)
   pass, and to revisiting e50f itself, not only to new Cyclone V ground.
3. **A vendor fact about one physical resource does not transfer to every logical consumer of
   it.** Two independently-correct, correctly-code-read findings can combine into a wrong result
   when one LE control bit or mux is shared by more than one logical function and a rule treats
   "the fact is true for consumer A" as "therefore true for consumer B". Confirmed twice in the
   same area of Cyclone IV's logic-element model, both on the gi-2 / DATAC mux: (a) during F-020's
   own development, an attempt to exclude carry-mode LEs from the ASDATA tie-to-1 rule was wrong
   and caused a severe regression, caught and reverted before that commit landed — carry mode uses
   gi 2 for both the comb function's carry-in AND the register's ASDATA, two logical roles sharing
   one mux, and the exclusion wrongly assumed one role implied the other; (b) F-021 (#183): the
   vendor-confirmed fact `LE_USE_REGISTER_FEEDBACK` (F-010) is true about the LE's **comb LUT's own
   DATAC pin** — it says nothing about whether the LE's **independent sload/ASDATA mux**, which
   physically shares the same gi-2 wiring, resolves to the same signal. A precedence bug that
   checked the comb-pin fact before the ASDATA mux's own lookup self-looped 5,228 of 5,237 image
   LEs on their own state forever; only 9 genuinely needed the fallback. Both bugs are the same
   shape: a real, correctly-sourced vendor fact, attributed to the wrong one of several logical
   consumers sharing one physical control bit or mux. **Consequence for Cyclone V**: when a vendor
   constructor/field is read as controlling one named function (a comb pin, a carry chain, a clock
   select), explicitly check whether the SAME mux or bit is dual-purposed for a second, distinct
   logical function elsewhere in the LE/block model before assuming the first reading generalizes —
   this is a modelling question to ask up front in Phase 1 (per-class writer-function pass), not
   something to discover only once a real design's behavioral test fails.

## 1. What caused the piecemeal pattern

Evidence says it was **(b) + (c) together**, not (a):

- **(a) is weak as the primary cause.** IV mostly did NOT defer "whatever the image doesn't use" —
  `docs/recovery-process.md` "Priority order" explicitly ranks "big regular blocks first (M9K =
  36% of the die)" over image-specific need, and the git log (`lifters/cycloneiv_clean/` history)
  shows systematic sweeps per block class (IO, then options, then LAB/M9K/MAC fields, then PLL,
  then clocks) — not "only what m2001 needs." `docs/cycloneiv-clean-gap-audit.md` §12 even flags
  transceiver/PCIe as "not checked" specifically BECAUSE the image doesn't exercise it, which is
  the deferral the task asks about — but this is one item among ~55, not the dominant pattern.
- **(b) is the dominant cause, proven by the gap audit's own untracked list.** No map of every
  control-bit class existed up front. `docs/cycloneiv-address-spaces.md` (the closest thing to
  "walk every address space") was written **late** — 2026-10-30, after dozens of prior commits had
  already hand-discovered CRAM/CFF/option-register boundaries piece by piece (compare commit dates:
  the address-spaces doc postdates `cycloneiv_clean` commits going back to `818a0f981`, the P0
  scaffolding commit, by weeks). Its own text admits the consequence: "74.34% of CRAM bits... are
  NOT shown to be reserved: the asmdb group vectors that would claim most of them... are not
  decoded" (section 1) — i.e. the map itself, written after most of the decode work, still can't
  say what's really unused vs. simply unwalked.
  - Gap-audit §16 "Found during this audit, not in any prior chat summary" is the direct evidence
    trail: stale `build.json` undecoded counters never reconciled against `cycloneiv-clean-m9k.md`
    prose (§16 bullet 1); the 75-instance IO-standard ambiguity — the single largest *named,
    counted* undecoded item in the whole image — had **no issue of its own**, only inline doc prose
    (§16 bullet 4, also §8); the 131-instance FF ASDATA gap and the 14/101-tile M9K output-CE/clear
    gaps are UNTRACKED as standalone issues (§3, §5); the transceiver/PCIe "verified absent" claim
    in `lightbridge-fpga.md` overstated what was actually checked (§12, §16 bullet 5) — these are
    gaps that were found by *surprise*, during an audit written at the end, not flagged by any
    up-front class inventory.
- **(c) is the mechanism that made (b) expensive.** `docs/recovery-process.md`'s own binding
  "Specimen rules for agents" section was written 2026-10-28 **in direct response to** the #141
  statistical detour — i.e. the batch-specimen discipline (Tier 0/1, one-feature-per-diff, yield
  floors) was itself a retrofit, not a starting design. Before that section existed, the case study
  in the same doc ("Case study: Cyclone IV #141") records: "no Phase-0 decision (both routes started
  the same day...)"; "the blocking fan-out decode was parked in a doc sentence, not an issue"; "the
  stopping rule compared relatives, never the absolute requirement" — all symptoms of specimens
  built one at a time, reactively, per blocked agent, rather than a batch matrix generated up front
  for a whole bit-class family. Outcome: four statistical stand-ins (#117, #136, #139, #140), gate
  pinned at ~4% for days.
- **(d) nothing else material found.** No evidence of a resourcing or tooling cause distinct from
  (b)/(c) — the Ghidra tooling (`docs/ghidra-workflow.md`) and the vendor-DB access existed
  throughout; the gap was procedural (when the map/writer-search/specimen-batch happened relative
  to the decode work), not capability.

**Conclusion for Cyclone V: (b) is the one to fix structurally** — build the full control-bit-class
map (Phase 0 below) BEFORE any image-specific decode starts, so gaps are discovered by inventory,
not by an end-of-project audit. (c) is already fixed procedurally by `docs/recovery-process.md`'s
binding specimen rules; Cyclone V inherits that for free — the task is to apply it as a **batch
pass per class**, never spawn-one-agent-per-blocked-bit again.

## 2. "Find the writer code first" — the actual ratio

`reference/rules.tsv` (158 rows incl. header, 157 data rows), status column (field 7):

| status | count | % of 157 |
|---|---|---|
| CONFIRMED_BY_CODE | 94 | 59.9% |
| SPECIMEN_ONLY | 55 | 35.0% |
| UNKNOWN | 8 | 5.1% |

Derivation column (field 4) tells the same story from a different angle: CODE 77, SPECIMEN 47,
MIXED 33 (MIXED = code locates the mechanism but a specimen still supplies part of the value, e.g.
L-002/L-004 below).

**CODE-first is markedly more durable.** `docs/reversing-errata.md` (72 numbered entries) is
almost entirely a record of SPECIMEN/fitted-era claims later corrected or refuted once the writer
function was found — CODE-derived claims essentially never appear as the WRONG side of an errata
row. Concrete cases, both exact matches to the task's ask:

1. **E-C1/E-C2/E-C3 — the whole learned/fitted coordinate model.** Per-column and per-source
   statistical routing tables, `Y mod 4` naming, held-out scores of 92.10%/17.4%/4.1%, a Jaccard
   clock-inversion bit guess — all **WRONG (removed)**, superseded once the fixed asm-to-plane
   function was read from code (`get_bits_from_source_to_dest` libddb_dygr 0x23bfe0): gate went
   5.42% -> 11.28% under the code-derived rule (v6). This is the #141 statistical detour itself,
   captured as errata.
2. **E-J1/E-L1 — the routing conduction rule.** The `lit_x` / `sel_x` variant-selection rule and
   "fan-in: not decided by the flags" were both **read off the corpus** (observed frequency,
   62.08% on a sample) before the code was found. Once `get_bits_from_source_to_dest` /
   `use_encoded_setting` / `is_encoded_bit_high` were decompiled, the real rule turned out to be
   "F0/F1 = delta running-sum parity, not a literal flag" — a different mechanism, not a
   refinement. The specimen-era 3.7-4.2% fan-in-conflict rate (E-L2) was an **artefact of the wrong
   rule**, not a real property of the design; under the code-derived rule it measured 0/64,375.
3. **E-A3/E-A5/E-T3 — the LUT INIT address/permutation saga.** Specimen-fit claims "dy negated,
   +23 fitted constant", a "+3" pool-base offset, and "cut_le_util pin permutation unresolved,
   identity order is specimen only" were each corrected once `calculate_bits_traditional` (asmdb)
   and `CUT_ATOM_CUDA_LE::get_assembler_lutmask` (libdb_cut) were read: no sign flip, no fitted
   constant (23 = dy_min + dy_max, a geometry fact not a fit), and no permutation at all (identity,
   confirmed by code, not merely by the 100% gate score it already had).
4. **E-P1/E-P3/E-Q4 — "obvious" specimen-era mechanisms disproved by code.** "No dedicated
   ASM_M9K*/ASM_RAM*/ASM_MULT* classes exist" was wrong — the classes exist in libraries
   (libcomp_asmram/asmmac/asmpll) that simply weren't in the Ghidra project yet; "physical cell =
   inverse of the written bit (die-flag inversion)" for M9K was wrong — `silent_set_bits` stores the
   value as written, and the apparent inversion was `ASMDB_SIMPLE_MUX::select`'s one-hot encoding
   with a `[1,0]` map, a different mechanism entirely.

**Durability verdict: SPECIMEN_ONLY-era claims were repeatedly wrong in ways a pure
diff-and-infer process could not have caught** — not just imprecise, but modeling the wrong
mechanism (statistical correlation standing in for a rule; an encoding effect mistaken for an
inversion). CODE-derived claims in the errata table are essentially never the refuted side. The
#141 postmortem (`docs/recovery-process.md`) generalizes this exact lesson into the binding Phase 0
rule ("vendor device DB... exact, complete" ranked above "minimal-diff specimens" above "open
projects").

## 3. "Constant / CRC / absent-feature, not a decode target" — checklist

Before spending specimen budget on an unexplained bit, cyclone IV turned up five distinct ways a
"gap" was not a gap at all. Test for these, in this order, before treating any unexplained bit as
a target:

1. **Is it a forced/default constant?** 130 of 160 option bits (35 forced + 95 default) read the
   constant `1` always, by `ASMDB_DIE::add_default_bit`/`add_forced_bit` list membership — not a
   per-design decode target, a vendor-fixed value (`docs/cycloneiv-address-spaces.md` §3.1,
   ledger O-002).
2. **Is it a checksum/CRC artefact of the container, not a stored option?** Errata E-R10: option
   bits 71/106/112 appeared to be "header cells with undecoded writers." Single-bit flips of the
   vendor sof showed they change NO rbf header byte at all — their cells are bytes 41/42 of frame
   0, the header **CRC-16**, which happens to move when those option bits move (both are inputs to
   the same checksum). Not a decode target; `cycloneiv_clean_options_build.rbf_cells` now drops
   those bytes. Same class: E-R7 (rbf header lane 0 byte 1 looked like it "followed package"; it is
   the USERCODE checksum, `compute_checksum`@0x3b6240) and E-F1 (a wrong zlib-header byte offset).
3. **Is the "second cell" actually a frame-end check cell, not a second data bit?** E-R8: 13
   "MISSING" IO sites were attributed to VREF overlap / bank-4 lead / a mysterious second CFF
   group. The real cause: 64 CFF bits each had a second 4-cell group that was a **frame-end check
   cell**, not a second value — flipping the tag bit alone moved only the primary group. Fixing the
   model (`data_groups`, primary-group-only) took MISSING sites from 13 to 0.
4. **Does the mode/feature exist in this die's hardware at all?** E-T4: MAC "accumulate / saturate
   / round / shift / chain" modes were treated as undecoded control bits. A survey of block 41's 17
   actual asmdb group types (`scripts/cycloneiv_clean_mac_survey.py`) showed **none of those group
   types exist** — the writer classes for them (`ASM_MAC_*SATAC/SHFTR/SMODE`) belong to *other*
   Altera families, not Stingray/Cyclone IV. Not a gap; a hardware-absence fact, confirmed from the
   asmdb survey, not merely inferred from absence of evidence. Same class: E-A1 (JTAG
   `OPTION_REG_JTAG_CORE_ACCESS` / `_USE_JTAG_PIN_SHARE` have no asmdb group on this die at all — 0
   bits in 197 pair builds); 11 of 15 JTAG classes similarly have no group (`docs/cycloneiv-clean-
   address-spaces.md` §4); TAP state machine IR/DR shift has **no address space, no sof tag, no rbf
   region** anywhere — hardened logic entirely outside the assembler's config model.
5. **Is the ambiguity electrical, not a decode failure?** Gap-audit §8: 75 IO-standard instances and
   44 IO-termination instances are CFF-bit-identical between several named standards (e.g. 2.5V vs.
   SSTL-2 Class I share one input buffer). Manual-review cross-check (A19/G1/A21) confirms these
   ARE electrically identical configurations on this silicon — not an unresolved decode, a
   **physically unresolvable** distinction. The audit explicitly flags: file this as "document as
   inherently ambiguous," not as a decode-gap issue.

Checklist to apply to Cyclone V before any bit-class goes on the Phase-2 specimen queue: (1) is it
in a default/forced list already, (2) does flipping it alone move any header/container byte that
isn't itself the target, (3) does a "second group" at the same nominal address actually move when
only the primary toggles, (4) does an asmdb survey of the die's actual group types show the
feature's writer class even exists on this die, (5) would two different "settings" produce
identical bits on every sampled build (electrical equivalence, not decode failure).

## 4. "Start from a validated die, not an unvalidated production-scale target" — not done for IV, and the cost

Dan: not doing this for IV (going straight at EP4CGX150, DJI's actual production die, with no
smaller die's engine already proven) was a mistake. Evidence of cost:

- **Impossible real-design counts, unusable as ground truth.** `recovery-process.md`'s own scoring
  rules (do-not-change section) state plainly: "V02 lifts to 2611 LUTs on a 1280-LUT device (203%)
  and V07 to 2636: impossible counts, so they measure lifter faults, not the design... Real-design
  LUT/FF/net counts are NOT a baseline." The project only has a trustworthy headline (oracle fault
  rate, not raw count) because it independently built a Diamond-rebuild oracle for a sibling family
  (ECP5/MachXO2) — for Cyclone IV the production die itself (EP4CGX150, 149,760 LEs) is far larger
  than anything a minimal specimen campaign naturally covers, so every image-level number needed
  its own from-scratch oracle-matching effort (`docs/cycloneiv-clean-image.md`) rather than
  inheriting trust from an already-closed, already-validated corpus on a smaller or at least
  already-proven die.
- **Phase-0 language already argued for starting small, and was not followed — but "small" is
  about specimen size, not the die itself.** `recovery-process.md` Phase 0 names "Minimal-diff
  specimens — 1-2 cells, one net, one feature per diff" and the Specimen rules section: "Smallest
  first. Tier 0: one hand-placed LUT, one net... Tier 1: two LUTs... Only then scale." The die
  (EP4CGX150, a mid-size production part) was never a *validated* engine target before full-scale
  work began on it — so even a "smallest possible" specimen still had to compile, place and route
  against an engine (lifter, decoder, oracle) that had never yet been proven correct on anything,
  collapsing the "prove the engine on something first vs. validate the production target" distinction
  one level up from specimen size.
- **Specimen-coverage and corpus-scale problems compound on a bigger die.** The gap-audit's
  M9K section alone needed per-tile checks across 542 M9K tiles (§5, §14) and the #178 investigation
  had to re-check "up to 542 of 542 M9K tiles" for a single write-enable convention bug found on 2
  tiles — a smaller die (fewer, more uniform M9K/LAB instances) would have made both the initial
  specimen sweep and the generalization check proportionally cheaper, with the same bit classes to
  learn. But this cost is about tile-array size, independent of whether any die had already been
  validated — it argues for picking a die with fewer repeat instances per tile class, not
  necessarily the die with the fewest ALMs overall.
- **The real mistake was not "picked too big a number."** It was starting production-scale decode
  work on EP4CGX150 (DJI's real part) before the engine had been proven against ANY die at all —
  there was no small, already-working reference point to fall back on when something went wrong,
  so every failure (the #141 statistical detour included) had to be debugged directly against the
  production-scale target with no simpler ground truth to triangulate from.

### The family's true smallest real part: 5CEA2, confirmed from the vendor product table

Checked directly (not from memory): `grep -rl "5CEA2\|5CEBA2\|5CSE\|5CST"` across every `.py`/
`.md`/`.toml`/`.json` file in this repo returns **zero hits** anywhere in `docs/`, `scripts/`,
`lifters/` (the only hits are gitignored agent-worktree copies of files already accounted for) —
this project has never worked with the family's true smallest part. The installed Quartus Prime
Lite 25.1 devinfo tree (`/mnt/2tb/opt/altera/quartus-25.1/quartus/common/devinfo/cyclonev/`) ships
devinfo for only the same 7 larger die families already in this project's docs (`d6_gtf150`,
`e50f`, `gt300f`, `gt75f`, `gx25f`, `sx120f`, `sx50f`) — no directory for the smallest part exists
in this install.

**Smallest real part, sourced**: Altera **Cyclone V FPGA and SoC FPGA Product Table, version
2025.09.24** (fetched from the theretroweb.com PDF mirror) names **5CEA2** (E-series; ordering
codes include 5CEBA2/5CEFA2) as the smallest device in the family:

| metric | 5CEA2 | gx25f (5CGXC3) | e50f (5CEBA4/5CEFA4-class) | d6_gtf150 (5CEBA7/5CEFA7-class) |
|---|---|---|---|---|
| LE | 25K | — | — | — |
| ALM | **9,430** | 13,460 | 18,480 | 56,480 |
| registers | 37,736 | — | — | — |
| M10K blocks | 176 (1,760 Kb) | — | — | — |
| MLAB | 196 Kb | — | — | — |
| variable-precision DSP blocks | 25 | — | — | — |
| 18x18 multipliers | 50 | — | — | — |
| PLLs | 4 | — | — | — |
| hard memory controllers | 1 | — | — | — |
| transceivers | **0** | — | — | — |
| PCIe hard IP | **0** | — | — | — |
| HPS / ARM core | **0** (E-series only; SE/SX/ST tie 5CEA2 on ALM at 9,430 but add a Cortex-A9 HPS, and SX additionally adds transceivers + PCIe) | — | — | — |
| packages | M383 (223-pin), U324 (176-pin), U484 (224-pin), F256 (128-pin), F484 (224-pin) | — | — | — |

5CEA2 (9,430 ALM) is smaller than every die this project currently has any data for, including
`gx25f` (13,460 ALM), which is only the smallest die family Quartus Lite's own installed devinfo
tree happens to distinguish — not the smallest part Altera/Intel actually shipped in this family.

### Phase 3 target: 5CEA2 specifically, not a shortcut through e50f/gt150f

Per Dan's explicit instruction, Phase 3 targets **5CEA2** as the FIRST Cyclone V die, even though
the project currently has zero vendor data for it (confirmed above) — this is expected, and is
exactly what Phase 0 (vendor-data acquisition) is for, not a reason to default back to `e50f` or
`gx25f` because they already have data. `e50f`/`d6_gtf150`'s existing corpus, decoder, lifter and
three independent oracles are production-scale confirmation (Phase 4) — they do not retroactively
satisfy "start smallest" just because a validated die already exists on a larger part. The lesson
from section 1 (IV went straight to its real production die with nothing smaller to triangulate
against) applies at the level of "has this engine been proven on the family's smallest part," not
merely "has it been proven on *some* part."

**Why smallest-first is not only about cheaper validation — the real reason is zero hard IP.**
5CEA2 is the E-series variant specifically *because* it has no transceivers, no PCIe hard IP, and
no HPS/ARM core (unlike the SE/SX/ST variants that tie it on ALM count but add that complexity
back in) — and it carries the fewest DSP blocks in the family (25 variable-precision blocks, 50
18x18 multipliers) while still having BOTH RAM types present (176 M10K blocks + 196 Kb MLAB). This
means Phase 0-2 (the address-space map, the batch writer-function search, the batch specimen
matrices) can go deep on every RAM type and every DSP mode the part actually has, on the simplest
possible M10K/MLAB set, **without any transceiver, PCIe or HPS complexity contaminating the fuzz
corpus or the writer-function search.** Smallest-first here means everything is quicker and
simpler to reason about, and — because there is no hard IP to get wrong — it is actually *easier*
to run deep, complex fuzzing across every RAM type and DSP mode the part supports than it would be
on a die where transceiver/PCIe/HPS bit classes are mixed into the same sweep.

Cold-start cost (CRAM geometry, a `device.db` entry, native tables, a fresh corpus, independent
oracle validation — section 1's citations explain why this is non-negotiable work) is real and is
paid once, on the family's smallest and structurally simplest die, rather than inherited later on
a larger die where the same class of bug (e.g. the IV 542-tile M9K generalization problem, section
4 above) is proportionally more expensive to find and re-check, and where hard-IP bit classes
(transceiver/PCIe/HPS) would otherwise have to be filtered out of the sweep by hand.

**DJI's actual production Cyclone V part(s)** (`docs/lightbridge-models-fpga-images.md`,
`docs/altera/cycloneV/cyclonev-status.md`), confirmed as Phase 4 targets, not Phase 3:
- air side (m1900, all 3 image variants): Cyclone V, **die byte 0x05 = e50f-class** — already
  validated in this project, but that is production-scale confirmation, not the smallest-first
  starting point.
- ground side (m2000/m2002/m2003): Cyclone V, **die byte 0x13 = `d6_gtf150`** (5CEBA7/5CEFA7,
  56,480 ALM) — already validated, same caveat.

**Recommendation:** Phase 3 for Cyclone V starts at **5CEA2** (9,430 ALM, E-series, zero hard IP),
building its vendor data, native tables, a small fresh corpus and oracle validation from scratch —
the same discipline this project already applied to e50f, applied this time to the family's
actual smallest and simplest die rather than a production-matched or merely-locally-available one.
`e50f` and `d6_gtf150`'s existing validation is reused only as Phase 4 (production-scale
confirmation against DJI's actual hardware), never as a substitute for Phase 3, and never (per
principle 2 in section 0) as the unexamined origin of a decode rule even when it is reused.

## 5. Phase plan for Cyclone V (batch campaign, not a reactive loop)

### Phase 0 — walk the full address-space / control-bit-class map, before touching any image

- Already available, not starting from zero:
  - **Mistral/Bluebird tables** (`docs/bluebird.md`): `cv_dies`, `cv_pram_strips`,
    `cv_route_muxes` (695,446 rows e50f), `cv_route_lines`, `cv_route_drivers`, `cv_p2r`, `cv_p2p` —
    device-wide routing *capacity* tables for all 7 dies, imported from Mistral's plain-text
    generator inputs (not reverse-engineered from compiled layout). This is a routing-capacity map,
    not yet a control-bit-class map — it tells you every mux Mistral's fuzzer found, not which
    asmdb group writes which CRAM address for M10K/DSP/IO/clock/PLL blocks the way
    `docs/cycloneiv-address-spaces.md` §2.1/§5 did for Cyclone IV.
  - **Quartus `.ddb` vendor files** (`docs/altera/cycloneV/cyclonev-ddb-format.md`): `*_hdr.ddb`
    parses exactly for all 7 dies (record counts verified: e50f 1,054,413, gt150f 2,847,246, etc.)
    — this is the Cyclone-V-specific analog of the IV `asmdb`/`asm.ddb` walk that eventually (too
    late) produced `docs/cycloneiv-address-spaces.md`. Do this walk FIRST for Cyclone V, not after
    image-specific decode has already started as it did for IV.
  - **Cyclone V-specific gap already identified**: `docs/altera/cycloneV/cyclonev-aes-conformance.md`
    and the "PARKED" rows of `docs/reversing-errata.md` (V-G1..V-G6) show Cyclone V claims to date
    are **ORACLE-ONLY (Mistral-derived)**, explicitly labeled as such, not yet CODE-confirmed —
    i.e. Phase 1 below (find-the-writer) has not started for Cyclone V at all. This is Phase-0
    output already recorded, not a new finding.
- **Deliverable of Phase 0**: one doc (`docs/altera/cycloneV/cyclonev-address-spaces.md`, modeled
  directly on the IV one) enumerating every address space (CRAM/CFF/PRAM/option-equivalent),
  every block type, and — critically — produced BEFORE Phase 1/2 start, not retrofitted after
  dozens of ad-hoc decode commits the way `cycloneiv-address-spaces.md` was (2026-10-30, long
  after `cycloneiv_clean`'s first commit `818a0f981`).

### Phase 1 — batch writer-function pass across ALL classes found in Phase 0

- For every block type / control-bit class Phase 0 names (LAB, M10K, DSP/MAC, IO, PLL/fPLL, clock
  network, config/option-equivalent, JTAG-equivalent), run the IV-proven writer-find recipe
  (`docs/ghidra-workflow.md` "Find the writer of a group": `ghidra_trace.py trace <GROUP_TYPE_NAME>`
  -> bound class + factory case + writer function + vtable slot + ctor table) **once, across every
  class, in one batch pass** — not one class at a time as an agent happens to get blocked on it.
- Record result per class immediately in a `reference/rules.tsv`-equivalent row, even when the
  answer is "no bound class found" (IV's own lesson, errata E-P1: libraries not yet in the Ghidra
  project, e.g. libcomp_asmram/asmmac/asmpll-equivalent for Cyclone V, stalled whole areas until
  imported — import ALL candidate writer libraries for Cyclone V up front, per
  `docs/reversing-lessons.md` lesson (a), rather than discovering the missing-import gap per class
  as IV did).
- **Per standing principle 3**: when a writer-function pass identifies what a mux/bit controls,
  explicitly check for a second, physically-sharing logical consumer (another function reading the
  same gi/mux slot for a different purpose) before recording the rule as generalizing to every
  context that mux appears in. Record both consumers' rules as separate rows even if they turn out
  identical — do not assume identity from a shared address.
- Apply the constant/CRC/absent-feature checklist (section 3 above) to every class BEFORE queuing
  it for Phase 2 specimens — this is what IV did reactively (E-R10, E-T4, etc. found mid-project)
  and should be front-loaded.

### Phase 2 — batch specimen generation per bit-class family, not per blocked bit

- For every class Phase 1 confirms has a writer but needs specimen confirmation of the value law
  (per `recovery-process.md`'s "Attributed" evidence level): generate the **whole matrix** of
  single-feature specimens for that class family in one batch (one Quartus build set, one diff
  pass) — e.g. all IO-standard x drive-strength x slew combinations for one block type in one
  sweep, not "whichever one bit happened to block an agent this week."
- Apply `recovery-process.md`'s binding specimen rules verbatim (Tier 0/1 smallest-first within
  the matrix, one-knob-per-pair, null controls first, yield floor stop criterion) — these rules are
  already generalized to "every family" (section "Specimen design (every family)") and need no
  Cyclone-V-specific rewrite, only batch-sized application.
- Bookkeeping: every parked sub-decode gets a numbered issue **at the moment it's parked** (already
  binding, `recovery-process.md` Phase 2) — the IV failure mode to avoid is a gap living only in a
  doc sentence or a `build.json` counter that silently goes stale (gap-audit §16's two
  reconciliation failures).

### Phase 3 — target the family's true smallest real part (5CEA2, 9,430 ALM, zero hard IP)

- Acquire vendor data for **5CEA2** specifically (E-series; ordering codes 5CEA2/5CEBA2/5CEFA2),
  confirmed from the Altera Cyclone V Product Table v2025.09.24 as the family's smallest real
  part (9,430 ALM) — smaller than every die this project currently has data for, including
  `gx25f` (13,460 ALM, only the smallest die Quartus Lite's own installed devinfo happens to
  distinguish, not the true smallest shipped part). This is Phase 0 work (vendor-data
  acquisition) applied to a die the project has zero existing references to — expected, not a
  blocker.
- Run the corpus/gate loop (Phase 1/Phase 3 of `recovery-process.md`, done-criterion corpus gate)
  against 5CEA2 first, using the Phase 0/1/2 outputs built for it. Smallest ALM count in the
  family means cheapest per-specimen compile and the fewest per-tile-class generalization edge
  cases (the IV M9K-542-tile lesson, section 4 above) before scaling up.
- **Zero hard IP is the structural reason to start here, not just the size.** 5CEA2 has no
  transceivers, no PCIe hard IP, and no HPS/ARM core, and carries the fewest DSP blocks in the
  family (25 variable-precision blocks, 50 18x18 multipliers) — while still having both RAM types
  present (176 M10K blocks + 196 Kb MLAB). Phase 1/2's writer-function search and specimen
  matrices can go deep on every RAM type and every DSP mode the part actually supports without any
  transceiver/PCIe/HPS bit classes contaminating the sweep — faster AND simpler to run complex,
  exhaustive fuzzing on, not a tradeoff between the two.
- This is also where the IV mistake of "corpus-wide numbers that are impossible / hard to trust"
  (section 4) is avoided: 5CEA2's small ALM count makes a from-scratch, independently-checkable
  corpus of real designs tractable in a way EP4CGX150-scale designs were not.

### Phase 4 — scale to the DJI production parts last

- Air side: validate against **e50f-class** (die byte 0x05) using the designs already compiled for
  m1900 (3 firmware variants, `docs/lightbridge-models-fpga-images.md`).
- Ground side: validate against **d6_gtf150** (die byte 0x13, 5CEBA7/5CEFA7) using m2000/m2002/
  m2003.
- Note this project is ALREADY at this phase for e50f/d6_gtf150 (status docs dated 2026-10-23
  through 2026-10-31) without having completed Phases 0-3 on the family's smallest part first —
  restarting the methodology at Phase 0/5CEA2 for the bit classes not yet CODE-confirmed (the
  V-G1..V-G6 PARKED rows) is the concrete fix this doc recommends, reusing the e50f/d6_gtf150 work
  already done as Phase 4 validation once 5CEA2's Phase 0-3 work exists, not discarding it.

## Summary table: IV lesson -> Cyclone V action

| IV evidence | Cyclone V action |
|---|---|
| Address-spaces map written late (2026-10-30), after ad-hoc decode had already started | Write the Cyclone-V address-space/class map (Phase 0) before any image-specific decode |
| 94/157 (59.9%) rules CONFIRMED_BY_CODE vs 55/157 (35.0%) SPECIMEN_ONLY; every errata WRONG-claim traced to a specimen-era guess later corrected by code | Batch writer-function search (Phase 1) across every class before any specimen campaign |
| Specimens built reactively, one blocked-agent at a time (pre-#141 fix) | Batch the specimen matrix per class family (Phase 2), per the now-binding rules |
| EP4CGX150 (mid/production-size) tackled directly; impossible real-design counts (V02 203%) the result | Start on 5CEA2 (9,430 ALM, family's smallest real part per the Altera product table, zero hard IP); e50f/d6_gtf150 as later Phase-4 validation |
| Gaps found by end-of-project audit (`cycloneiv-clean-gap-audit.md`), several UNTRACKED | File every parked class/sub-decode as an issue at Phase-1/2 time, not discovered by a retrospective audit |
| No principle against trusting inherited data (the fitted coordinate model and the specimen-frequency routing rule both leaned on "this already works") | Standing principle (section 0.2): inherited corpus/table data, including this project's own e50f corpus, is a check, never the origin of a decode rule |
| A vendor fact correctly read for one logical consumer of a mux (the comb-pin feedback flag, F-010) was wrongly assumed to generalize to a second, physically-sharing consumer (the ASDATA/sload mux) — same shared-resource shape as a carry-mode exclusion bug caught earlier in the same code's own development; both self-looped or mis-decoded real LEs, one of them in the shipped DJI image (F-021, #183), only caught once a real design's behavioral test ran against current code | Standing principle (section 0.3): when a writer-function pass names what a mux/bit controls, explicitly check for a second logical consumer sharing the same physical wiring (Phase 1 action item) before recording the rule as general |
