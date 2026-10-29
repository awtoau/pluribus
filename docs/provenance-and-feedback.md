# Provenance and feedback — evidence tiers for recovered bit meanings

Design for marking every recovered meaning (bit, mux input, wire driver, cell field) with HOW it was
obtained, and for feeding contradictions back into everything that shares the same reasoning.
Companion to [recovery-process.md](recovery-process.md) (method) and
[cycloneiv-bit-inventory.md](cycloneiv-bit-inventory.md) (coverage metric). Issue #141. Status: IMPLEMENTED
(commit b5e1dea13 and after). The real DDL is `schema.py`; table-by-table reference is
[provenance-schema.md](provenance-schema.md). Section 4 sketches are the original design, superseded by those two.

Position under analysis (Dan, 2026-10-29): brute force is guaranteed; patterns predict because the
die is a grid; every predicted or statistical meaning is MARKED so a wrong prediction leads back to
all its siblings; always feedback.

Verdict in one line: marking + feedback is right and overdue; "guaranteed" holds only for the
observable, single-variable, fitter-pinnable part of the question space, and on Cyclone IV the
per-tile brute force is ~100+ days, so patterns are not an optimisation — they are what makes the
method affordable, and the rolling audit is the price of using them.

## Glossary (ONE definition; every other doc, script comment and the coverage page use these names)

| name | key (ledger / page) | meaning | rule |
|---|---|---|---|
| verified | `verified` | compared claim-for-claim against a vendor oracle | `provenance/tiering.py` |
| measured | `measured` | raw diff or observation at that cell or site | exact evidence rows, no pattern |
| sampled (= verified-by-sampling) | `sampled` | a pattern confirmed at >= N distinct scopes (N = 3 for 1-D, 5 for 2-D, extremes of every axis included), zero refutations | `tiering.sampling_bar`; N and misses on the row; its OWN line beneath the headline, labelled 'rule verified by sampling (not exact per cell)'; never added into the headline (#157 decision 4) |
| pattern-predicted | `predicted` | a rule fitted to measured parents and applied beyond them, below the sampling bar | revocable by one miss |
| decoded (= decoded-untested) | `decoded` | read from the vendor decode; nothing tested at the cell | |
| statistical | `statistical` | last-resort fit/vote where no exact route exists; unverified | its own tier, never merged into counts above; replaced when an exact source covers it |
| suspect | `suspect` | a pattern or claim with a recorded miss or a conflict | revoked from verified tiers until audited |
| refuted | `refuted` | contradicted by a specimen inside its scope | |
| unknown | `unknown` | nothing attributes a meaning (the headline) | |
| headline exact | `die_headline_exact` (ledger metric) | verified + measured only: exact evidence per cell; the one coverage number on the page tiles, progress table and ledger summary line | derived from tier keys when absent in old rows; `sampled` never added |
| projected unused | `unknown_projected` | SUB-LINE of unknown: unknown cells set in none of the n held bitstreams | triage by frequency; not a claim, not a tier, never pattern-predicted, never subtracted from unknown |

- Claim `tier` (how obtained: measured, vendor-decoded, eliminated, pattern-predicted, statistical, ...) and claim `status` (open, confirmed, verified-by-sampling, suspect, refuted, ...) are the DB vocabulary (section 2); the names above are the coverage tiers computed from them.
- Evidence LEVEL (1 set, 2 attributed, 3 isolated, 4 hardware; recovery-process.md "Single-bit confirmation") is stored per specimen-pair row in `evidence.result["level"]` (JSON, not a column); counts are never mixed across levels.

## 1. Is brute force guaranteed?

### Conditions under which it is

| condition | meaning | Cyclone IV status |
|---|---|---|
| finite, enumerable question space | every (mux, input) / (block, parameter) can be listed from a source other than the bitstream | yes: routing.ddb gives 14,862,095 real mux inputs over 1,379,388 blocks; LE/M9K/DSP parameters are the WYSIWYG primitive lists |
| each specimen yields one unambiguous raw diff | base and specimen differ in ONE thing; diff = set bits in one plane only; rebuild identical | yes where tried: Tier 0/1 LE pairs, 240-pair LOCAL_LINE grid x4 LABs, M9K p0 (1 cell, stable x4) |
| the fitter can be pinned | placement by LOCATION, routing by RCF back-annotation, same tool version, same seed | mostly: LOCATION exact; RCF forcing accepted for some elements, `rerouted` / `rejected` for others (`rcf_fuzz_bits.status`) |
| the diff is attributable | the flipped bits belong to the varied thing, not to a side effect | NOT in general: see shared select bits, port permutation below |

When all four hold the answer is exact and the only cost is builds. The failures below are where
one of them does not hold.

### Where it is not guaranteed, or is expensive (Cyclone IV)

| case | why brute force fails or balloons | fallback | mark result as |
|---|---|---|---|
| fitter honours only legal routes | an RCF forcing an input the fitter considers illegal is rerouted; the question "what does input k mean" cannot be asked directly | reach k from a different source/sink pair; else leave unasked | `unknown` with reason `unforceable`; never infer from neighbours |
| port permutation | fitter swaps LUT inputs (dataa..datad) and rewrites lut_mask; "one net moved" becomes "net + mask + port" | `dont_touch`, pin the port in post-fit; accept only when post-fit shows the intended port | `measured` only if post-fit confirms the port; else discard the pair |
| shared select bits | one second-level bit serves up to 12 inputs of a mux, and one block can hold several muxes; the diff shows the bit but not which mux consumed it | diff-of-diffs (vary only the input, only the source); key answers by GROUP (cycloneiv-specimens.md) | `measured` at group granularity; the block->wire attribution stays `vendor-decoded` |
| context-dependent bits | a bit only changes when a second setting is present (e.g. output-register bit with the register enabled) | 2^k factorial over the k interacting parameters, k small; otherwise single-variable laws | `measured` with `scope.context = {setting: value}`; a claim outside its context tuple is `pattern-predicted` |
| IP blocks need combinations | M9K mode x width x port x clocking is a product space (~5 x 9 x 2 x 8); DSP similar | measure each axis alone (the checklist), predict the product | axis entries `measured`; cross terms `pattern-predicted` by `m9k-axes-independent` until a factorial sample confirms |
| options only settable by stream options | header frame 0 option bits (159 unknown), compression flags — set by `quartus_cpf`, not by the design | separate option-sweep specimens (one option per pair) | `measured` with `subject_kind = stream-option` |
| unobservable bits | bits no legal design sets (redundancy, test, factory) | none; they cannot be measured | `never-exercised` after evidence of absence (next subsection); counted in the inventory, never predicted, never "understood" |
| coordinate map between sources | asm frame axis != plane frame axis near M9K/DSP columns (AFX != FX on 7 LAB columns; vendor x not a pure mirror, +1 after each M9K/DSP pair, 24/104 columns) | per-column anchor specimen (one LE_BUFFER fan-out per column) | the map itself is a claim: `pattern-predicted` per column until that column has an anchor |

### Never-exercised bits (Dan, 2026-10-29)

Specimens come from the vendor fitter, so a bit the fitter never sets is invisible to the method.
"Never set in N builds" and "not yet tried" look identical until the absence is itself recorded.

Categories, and how each is told apart from "not yet tried":

| category | why the fitter never sets it | distinguishing test | bounded by |
|---|---|---|---|
| cost-model preference | a legal pip the fitter never picks (longer, slower, worse congestion) | RCF forcing succeeds -> it was preference, now `measured`; refused with Info 170085 -> not this category | ddb fan-out (the pip exists) |
| illegal / unusable choice | pip or mode the device rules forbid (a listed mux input whose source wire never exists at that tile; a mode the primitive rejects at compile) | RCF forcing refused (170085) at every source/sink pairing that names it; Quartus error on the primitive parameter | ddb fan-out lists it, fitter legality rejects it |
| mode- / IP-context only | bit changes only inside a mode the specimen set has not entered (DCS, HSSI, remote update, M9K ECC, PLL reconfig) | enumerate the primitive's mode parameters; a bit never flipped by any single-parameter pair of that primitive is context-dependent, not absent | primitive parameter lists (WYSIWYG) + handbook mode tables |
| stream-option only | set by `quartus_cpf` / device options, not by the design (header frame 0: 159 unknown) | option sweep, one option per pair | the options list of the tool |
| spare / reserved / test / redundancy | no vendor table references the bit; no option or primitive touches it | no asm entry, no ddb node, no primitive parameter, zero set across the corpus AND the third-party image set | nothing — these are the residue |
| other-tool reachable | set by a different Quartus version / setting / hand-edited stream, not by ours | corpus of third-party images: a bit set there but never by us is reachable, so `unknown(reason=unasked)`, never `never-exercised` | the image corpus |

Reach extension by RCF-as-input (forced routes):

- Quartus honours a back-annotated route when the alternative is legal and refuses an illegal one
  (Info 170085, element dropped and rerouted). So the bound on reach is LEGALITY, not fitter
  preference: every ddb pip that forcing can name is reachable in principle; a forcing refusal at
  every pairing is evidence the pip is illegal at that tile.
- Forcing covers routing only. Cell/IP configuration bits are reached by parameters; stream
  options by `quartus_cpf`. Each has its own "all attempts refused" form.
- Not every refusal is legality: a refusal with the wrong sink port, a source the chain cannot
  place, or a conflicting LOCATION is a bad specimen. An absence record counts only refusals
  where the diagnostic names the forced element.

Evidence of absence (one `evidence(kind=absence)` row per bit set, never per bit):

| field | content |
|---|---|
| bits | the scope (frames x v, or a tile class x offset band) |
| builds | N designs that touch the enclosing tile/block and never set any of them |
| forced | K forcing attempts naming the element, each with the refusal diagnostic (170085 or compile error) |
| settings | tool versions, seeds, fitter effort, optimisation modes tried |
| corpus | third-party image set checked (count, which set never any of the bits) |
| static | what references the bits: none / asm group / ddb node / primitive parameter |
| commit | when recorded |

Tier `never-exercised` (believed unreachable):

- Assigned only from an absence row with `forced >= 1` for routing-class bits (or every parameter
  of the owning primitive tried for cell-class bits) AND zero set across the image corpus.
- Not `verified`, not "understood", not predicted from. Inventory shows it as its own line with
  its absence evidence summary; coverage % counts it in the denominator (below).
- Without the absence row the bit is `unknown(reason=unasked)`; "we never saw it" is not evidence.
- **Headline composition (Dan, 2026-10-29):** headline unknown = die_bits - (verified + measured + sampled + predicted + decoded + suspect + refuted). "Set in none of N held designs" is a triage sub-line under unknown with N stated; it is never a tier, never subtracted from the headline, never `pattern-predicted`. The tier vocabulary is closed: no new label without a doc change in the same commit.

Denominator split:

- `die_bits = shown_reachable + not_shown_reachable`. `shown_reachable` = bits with at least one
  measured, vendor-decoded or image-corpus hit; `not_shown_reachable` = `never-exercised` +
  `unknown`. Coverage is reported twice: known / shown_reachable (the method's own progress; can
  reach 100 %) and known / die_bits (what a lift can trust; never reaches 100 % while any
  `never-exercised` remains).
- A lifted image sets a bit in `never-exercised` or `unknown` -> that bit is a FAULT in the lift
  report, counted beside missing/extra/wrong, and the bit is immediately promoted to
  `unknown(reason=seen-in-image)` with the image as evidence. Hand-edited streams, other Quartus
  versions and settings can set bits our fitter never does; the lifter must report them, never
  ignore them as noise.

Static sources that bound the reachable set, in order of strength:

| source | bounds | does not bound |
|---|---|---|
| routing.ddb fan-out (14.9 M real inputs) | which mux inputs exist per tile (legal pip universe) | whether the fitter can be made to pick one; cell/IP bits |
| asm.ddb groups (51.6 M entries, 7.6 M distinct positions) | which (frame, v) cells routing can ever touch | the 1.5 M out-of-band entries (M9K bulk / interface) and cells no entry names |
| WYSIWYG primitive parameter lists | cell/IP configuration bits | which parameter combinations the compiler accepts |
| `quartus_cpf` option list | stream-option bits | — |
| third-party image corpus | bits SOME tool set (reachable by existence) | meaning |
| nothing | the residue: cells no table, parameter, option or image references | — |

A bit in the residue after every row above is the only candidate for `never-exercised` on
static grounds; it still needs the absence row before it gets the tier.

Later hit (a bit finally exercised):

- A specimen, audit or lifted image sets a `never-exercised` bit -> `claim_events(hit)`; tier
  becomes `measured` (specimen) or `unknown(reason=seen-in-image)` (image), the absence row is
  kept and marked `superseded` (its "forced refused" entries are now data about the fitter, not
  about the silicon).
- The absence CATEGORY that was claimed (illegal / reserved / ...) is the pattern here: every
  other `never-exercised` set assigned on the same grounds (same forcing diagnostic, same static
  residue rule) goes `suspect` and gets re-tried first in the audit queue. The loop in section 3
  applies unchanged; the "pattern" is the absence rule.
- `shown_reachable` grows, both coverage ratios move, the ledger records which.

### Cost (build-bound)

Measured 2026-10-28: 12–20 s per Quartus build at 20 parallel chains inside the lease budget (`heavy_guard.LEASE_BUDGET_GB`, `MIN_AVAILABLE_GB`)
(`build_pool`); call it ~3,500 pairs/hour. Host limits: `scripts/heavy_guard.py` constants (memory-budget.md).

| question space | size | builds (pairs) | wall clock | tractable? |
|---|---|---|---|---|
| every mux input, every tile, raw diff | 14.9 M inputs | 14.9 M | ~180 days | no |
| every mux input, one tile per (class x position), 32 classes x 3 | ~1,000 inputs/tile x 96 | ~10^5 | ~30 h | yes, with pattern |
| LOCAL_LINE grid, one LAB (done) | 16 x 15 | 240 | 4 min | done x4 LABs |
| LOCAL_LINE grid, every LAB | 9,360 LABs | 2.2 M | ~27 days | no — pattern + audit |
| M9K init address/bit law, one site | 14 addr + 9 bit + 9 widths | ~40 | 1 min | yes |
| M9K law, 3 sites x 8 columns | x24 | ~1,000 | 20 min | yes |
| M9K every cell, one site | 9,216 | 9,216 | 2.6 h | yes but pointless once the law holds |
| bonded pins in + out (done) | 451 x 2 | 902 | 15 min | done |

Conclusion: exhaustive per-tile enumeration is affordable only for one tile per class. Everything
else rests on a pattern, so the pattern must carry its evidence and be audited (section 3).

## 2. Evidence-tier model

### Source tier (closed vocabulary; fixed at creation, never promoted)

| tier | how obtained | example today |
|---|---|---|
| `measured` | raw diff of a specimen pair; same tool version; rebuild identical | `wires_tile` / `lis_tile` phys-map entries; M9K p0 cell (frame 1111, v 2805) |
| `vendor-decoded` | read from the vendor device DB through a decoder whose own correctness is a claim | asm.ddb group bits; routing.ddb fan-out graph; `group k == edge k` rule |
| `pattern-predicted` | a law fitted to measured parents and applied beyond them | LOCAL_LINE translation to 9,356 LABs; class-wide `specimen` entries; LUT INIT anchor law; `afx_map` mirror |
| `statistical` | voted / learnt over many builds; no single build proves it | phys-map `wires` / `lis` / `defaults` / `cells` votes; `asm_names` alias sets; 1c clock-polarity fit |
| `eliminated` | the only remaining candidate after every other meaning in a finite set is measured | not used yet (M9K residual bits will be the first) |
| `never-exercised` | believed unreachable by the vendor fitter: an absence row (N builds, K refused forcings, settings, zero image-corpus hits, static residue) — section 1; not verified, not understood, not predicted from | none assigned yet (needs the absence rows) |
| `unknown` | nothing attributes a meaning; carries a `reason` (`unasked`, `unforceable`, `seen-in-image`, `orphan`, `conflict`) | inventory classes 4a–4e, 5c, 6 |

A derived claim's tier is the WEAKEST tier in its evidence chain: asm bits are `vendor-decoded`,
but placing them needs `afx_map` (`statistical`), so the placed asm claim is `statistical` until the
column has a measured anchor. Today's inventory counts 2a/2b as "evidence"; under this rule most of
it is `statistical`.

### Status (moves; this is where promotion/demotion lives)

| status | rule |
|---|---|
| `open` | created, no independent confirmation |
| `confirmed(n, scopes)` | n specimens at n distinct scopes agree; scope list recorded |
| `verified-by-sampling` | `pattern-predicted` only: confirmations at >= N distinct scopes (N = 3 for a 1-D law, 5 for 2-D), at least one at each scope extreme, zero refutations. Never becomes `measured`. |
| `oracle-verified` | compared claim-for-claim against a vendor post-fit oracle on an independent design set (the 1a LUT INIT case: 301 designs, 5,354,496 bits) |
| `suspect` | a sibling of the same pattern was refuted, or two exact sources disagree; stays until an audit at this scope clears it |
| `refuted` | a specimen inside the claim's scope contradicts it |
| `superseded` | replaced by a stronger-tier claim with the same subject + scope (the statistical->exact replacement rule in recovery-process.md) |

"Verified" means `oracle-verified` or `verified-by-sampling`; nothing else. Inventory/ledger
headlines report tier x status, never a single word, and two coverage ratios: over
`shown_reachable` and over `die_bits` (section 1, denominator split).

### Prediction record (one row of `claims`, section 4)

| field | content |
|---|---|
| claim | subject kind + key: `bit-meaning (frame,v) = "LI 7 select for src LE3"`, `mux-input (block, group) -> wire`, `cell-field (M9K, word w, bit b) -> (frame, v)` |
| pattern_id | the law applied (`ll-translate-v1`, `lut-anchor-v2`, `afx-mirror-v1`); NULL for `measured` / `vendor-decoded` |
| parents | evidence ids of the measured specimens the pattern was fitted to |
| scope | where it is applied: `{class, x_range, y_range, columns, widths, context}`; per-tile override = scope of one tile |
| confidence_basis | why we believe it here: `"3 positions agree; interior only"`, `"vote 317/318 over 410 builds"` |
| created_commit | commit that introduced the claim (ties to the coverage ledger) |
| status | as above, plus confirmation count + refutation count |

### Mapping today's artefacts

| artefact | tier | status | note |
|---|---|---|---|
| phys_map `provenance: specimen`, class-wide (`wires`, `lis`) | `pattern-predicted` by `class-generalise-v1` | `confirmed(2–3)` | the string says `specimen`; the CLAIM is class-wide from 2–3 positions — the tier belongs to the claim, not the source |
| phys_map `wires_tile` / `lis_tile` | `measured` | `open` | scope = one tile; the per-tile overrides of the model |
| phys_map voted `wires` / `lis` / `defaults` / `cells` (no provenance string) | `statistical` | `open` | 4/4 agree with specimens where they overlap; the other ~2,900 never checked |
| `li_map.json` | `statistical` | `open` | 540 resolved of 3,750 |
| inventory 1a LUT INIT | `pattern-predicted` by `lut-anchor` | `oracle-verified` (301 designs) | never `measured`: the anchor law came from fuzz builds |
| 1b LE-used bit | `pattern-predicted` | `suspect` | 14/1,018 misses on one design = refutations nobody acted on |
| 1c clock polarity | `statistical` | `open` | Jaccard 0.85 |
| 2a / 2b asm cells | `statistical` (weakest link = `afx_map`) | `open` | bits themselves `vendor-decoded`; 83 % learner agreement is a triage number, not a confirmation |
| 3 LOCAL_LINE translated | `pattern-predicted` by `ll-translate-v1` | `confirmed(4)`: X10Y10 parent + 3 held-out | edge rows y1/y90 and M9K-adjacent columns are OUTSIDE the parent scope and must be flagged as such |
| ddb_map (`group k == edge k`) | `vendor-decoded` | `confirmed` on wires (3,479/3,490), `suspect` on LI (1,073 wrong) | one rule, two statuses by subject kind |
| LI band: ddb vs specimen on 6 class keys | both `suspect` | `conflict` | two exact-claimed sources disagree; neither counts as known until adjudicated |
| specimen LOCAL_LINE answer at X10Y10 (240 pairs) | `measured` | `confirmed(1)` by rebuild | the parent of `ll-translate-v1` |
| 5b CRC bytes | `measured` (recomputed 70/70) | `oracle-verified` | checksum meaning only |

## 3. The feedback loop

### Negative loop — a specimen contradicts a claim, or an outlier appears

Trigger: a new `evidence` row lands whose scope intersects an existing claim and disagrees (bit set
where the claim says clear, wrong wire, wrong cell). A single outlier counts (1b's 14 misses, the
LI-band 1,073).

| step | action | output |
|---|---|---|
| a | the intersecting claim -> `refuted`; event logged with the evidence id | `claim_events(refuted)` |
| b | its pattern -> `suspect`; EVERY claim citing that pattern -> `suspect` (one UPDATE over `claims.pattern_id`) | sibling list, count, die bits affected |
| c | auto-queue audit specimens for the same pattern at OTHER scopes, ranked by die bits the sibling claims cover; first the scope extremes (edge columns, last row, widest width) and the scope nearest the refutation | `tmp/audit_queue.json` consumed by the specimen tools (`gen <set>`) |
| d | re-run the inventory: `suspect` and `refuted` leave the known columns and appear as their own line; die coverage % drops accordingly; `--record` writes the drop to the ledger with the commit | ledger line with a negative delta and the pattern id in `subject` |
| e | one issue comment per event (pattern id, evidence id, siblings count, bits affected); a new issue only when no open issue owns that pattern | numbered trace |

A pattern leaves `suspect` only when every queued audit at distinct scopes confirms it AND the
refutation is explained by a narrower scope (the pattern gets a smaller scope, the refuted region
becomes `unknown(reason=conflict)` or gets its own measured claim). "Mostly holds" is not an exit.

### Positive loop — held-out specimens confirm a claim

- Each confirmation inside a claim's scope: `confirmations += 1`, scope appended to `confirmed_scopes`, event logged.
- A pattern's `verified_scope` widens only to the hull of its confirmed scopes, never beyond (a law confirmed at columns 10, 37, 58, 100 is verified for interior LAB columns 10–100, not for edge columns or M9K-adjacent ones — those are separate classes per the edge rule).
- Graduation to `verified-by-sampling` per the N rule in section 2; still `pattern-predicted` tier.
- A `statistical` claim confirmed by a specimen does not get promoted; it is `superseded` by the new `measured` claim (same subject, narrower scope) and the remaining statistical scope stays `statistical`.
- A `never-exercised` bit that gets hit is promoted as in section 1 ("Later hit"); the absence rule that assigned it is treated as a pattern, so its other assignments go `suspect` and head the audit queue.

### Sampling rule — errors must surface without a contradiction

- Audit budget: 10 % of all specimen builds are audits of existing claims (at ~3,500 builds/h this is ~350 audits/h when a sweep runs, ~0 when idle — so also a floor: >= 20 audits per inventory run).
- Selection: seeded random over (pattern, scope cell) pairs weighted by die bits covered and by age since last audit; never a scope already audited; `suspect` patterns first; a new pattern gets 3 held-out audits before it counts in coverage at all.
- Every audit result is an evidence row like any other — confirmation or refutation feeds the loops above.
- A pattern with zero audits in the last 2 inventory runs is shown in the inventory as `stale` (not demoted; visible).

## 4. DB design (original sketches; IMPLEMENTED in `schema.py`, see provenance-schema.md)

The sketch had five tables; the implemented schema has 21 (scopes, evidence_scopes, expectations, unknowns, audits, matchers, corpus/gate tables added). SQLite default, PostgreSQL optional; lists as JSON per CLAUDE.md. Granularity is
pattern + scope, never per bit: per-bit expansion is computed (numpy, as the inventory already does).

```python
# One row per measurement or decode event. Specimen pairs cite corpus_builds; vendor decodes cite
# the decoder script + the DB file hash; oracle compares cite the design set.
evidence = Table("evidence", metadata,
    Column("id",          Integer, primary_key=True, autoincrement=True),
    Column("kind",        Text, nullable=False),   # specimen-pair | vendor-decode | oracle-compare | audit | elimination | absence | image-hit
    Column("family",      Text, nullable=False),
    Column("device",      Text, nullable=False),
    Column("build_base",  Integer, ForeignKey("corpus_builds.id")),    # NULL for vendor-decode
    Column("build_spec",  Integer, ForeignKey("corpus_builds.id")),
    Column("tool_version", Text),
    Column("stable",      Boolean),                 # rebuild gave identical bits (NULL = not rebuilt)
    Column("result",      JSON, nullable=False),    # raw diff [[frame, v], ...]; decoder digest; absence: {builds, forced:[{element, diag}], settings, corpus, static}
    Column("commit",      Text, nullable=False),
    Column("created_at",  DateTime(timezone=True)),
    UniqueConstraint("kind", "build_base", "build_spec"),
)

# One row per law. id is a slug (ll-translate-v1); a changed law is a NEW id, never an edit.
claim_patterns = Table("claim_patterns", metadata,
    Column("id",            Text, primary_key=True),
    Column("family",        Text, nullable=False),
    Column("description",   Text, nullable=False),
    Column("law",           JSON, nullable=False),   # parameters: {frame: "FX[x]+rel", v: "20+70*y+rel"}
    Column("parents",       JSON, nullable=False),   # evidence ids the law was fitted to
    Column("status",        Text, nullable=False),   # open | confirmed | verified-by-sampling | suspect | refuted | retired
    Column("confirmations", Integer, nullable=False, server_default="0"),
    Column("refutations",   Integer, nullable=False, server_default="0"),
    Column("verified_scope", JSON),                  # hull of confirmed scopes
    Column("created_commit", Text, nullable=False),
)

# One row per (subject, scope). Most-specific scope wins at lookup (per-tile override beats class).
claims = Table("claims", metadata,
    Column("id",           Integer, primary_key=True, autoincrement=True),
    Column("family",       Text, nullable=False),
    Column("device",       Text, nullable=False),
    Column("subject_kind", Text, nullable=False),  # bit-meaning | mux-input | wire-driver | cell-field | coord-map | stream-option
    Column("subject_key",  Text, nullable=False),  # e.g. "LI:7|src:LE3", "block:12345|group:2", "M9K:init"
    Column("scope",        JSON, nullable=False),  # {class, x:[lo,hi], y:[lo,hi], columns, widths, context}
    Column("scope_key",    Text, nullable=False),  # canonical string of scope (for the unique constraint)
    Column("meaning",      JSON, nullable=False),  # the answer: [[frame_rel, v_rel], ...] or wire id or law instance
    Column("tier",         Text, nullable=False),  # measured | vendor-decoded | pattern-predicted | statistical | eliminated | never-exercised | unknown
    Column("status",       Text, nullable=False),
    Column("pattern_id",   Text, ForeignKey("claim_patterns.id")),   # NULL unless pattern-predicted
    Column("evidence_ids", JSON, nullable=False),  # direct supporting evidence (measured: the pair; predicted: the parents)
    Column("n_bits",       Integer, nullable=False),  # die bits this claim covers (for ranking + coverage)
    Column("inventory_class", Text),               # 1a..6 (ties to the ledger)
    Column("confidence_basis", Text),
    Column("created_commit", Text, nullable=False),
    Column("updated_at",   DateTime(timezone=True)),
    UniqueConstraint("device", "subject_kind", "subject_key", "scope_key"),
)
Index("idx_claims_pattern", claims.c.pattern_id)
Index("idx_claims_tier", claims.c.device, claims.c.tier, claims.c.status)

# Append-only history; the feedback loop writes here, nothing deletes.
claim_events = Table("claim_events", metadata,
    Column("id",          Integer, primary_key=True, autoincrement=True),
    Column("claim_id",    Integer, ForeignKey("claims.id", ondelete="CASCADE")),
    Column("pattern_id",  Text, ForeignKey("claim_patterns.id")),
    Column("event",       Text, nullable=False),   # created | confirmed | refuted | suspect | cleared | superseded | audited | stale
    Column("evidence_id", Integer, ForeignKey("evidence.id")),
    Column("commit",      Text, nullable=False),
    Column("ts",          DateTime(timezone=True), nullable=False),
    Column("detail",      JSON),                   # {siblings: n, bits_affected: n, scope: ...}
)
Index("idx_claim_events_pattern", claim_events.c.pattern_id, claim_events.c.ts)

# Per recovered object per bitstream: the weakest tier among the claims the lifter used.
lift_provenance = Table("lift_provenance", metadata,
    Column("id",          Integer, primary_key=True, autoincrement=True),
    Column("bitstream",   Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("object_kind", Text, nullable=False),   # lut | ff | arc | net | hard-cell
    Column("object_key",  Text, nullable=False),
    Column("min_tier",    Text, nullable=False),
    Column("min_status",  Text, nullable=False),
    Column("claim_ids",   JSON, nullable=False),
    UniqueConstraint("bitstream", "object_kind", "object_key"),
)
```

### Queries

| question | SQL sketch |
|---|---|
| everything predicted by pattern P | `SELECT * FROM claims WHERE pattern_id = :P` (plus `SUM(n_bits)` for the bits at stake) |
| everything resting on specimen S | `SELECT * FROM claims WHERE evidence_ids LIKE '%"S"%'` (SQLite: `json_each(evidence_ids)`; PG: `@>`), UNION the claims of every pattern whose `parents` contain S |
| what changes if S is wrong | the query above, then `SELECT pattern_id, COUNT(*), SUM(n_bits) ... GROUP BY pattern_id` — the blast radius by pattern; plus `lift_provenance` rows citing those claim ids for the netlist impact |
| coverage by tier per class per commit | `SELECT inventory_class, tier, status, SUM(n_bits) FROM claims WHERE device=:d GROUP BY 1,2,3`; the inventory's `--record` writes this breakdown per class instead of the fixed `LEDGER_TIER` map; unknown = die bits of the class minus the sum; `shown_reachable` = die bits minus (`never-exercised` + `unknown`) |
| image sets a bit outside shown_reachable | `SELECT * FROM claims WHERE tier IN ('never-exercised','unknown')` intersected with the image's set cells (numpy); each hit -> `evidence(image-hit)` + `claim_events(hit)` + a lift fault |
| audit queue | `SELECT pattern_id, scope FROM claims WHERE status IN ('suspect','open') ORDER BY (status='suspect') DESC, n_bits DESC` excluding scopes already in `claim_events(event='audited')` |

### How the lifters consume it

- The lifter resolves each lookup through `claims` (most-specific scope wins) and records, per recovered object, the claim ids it used and the min tier/status — `lift_provenance`.
- `report.py` adds one line: "N cells / M nets rest on predicted claims, K on statistical, J on suspect". A netlist with any object on a `refuted` claim fails the gate.
- Lookup cost: claims are loaded once per lift into an in-memory index keyed by (subject_kind, class) — ~10^4–10^5 rows, same order as today's phys map, which is itself the first thing to migrate into `claims`.

## 5. Risks

| risk | mitigation |
|---|---|
| provenance rot — claims outlive the scripts/commits that produced them | `created_commit` + `evidence.commit` mandatory; regenerate-from-evidence script is the canonical path (derived artefacts have no legacy); a claim whose evidence row is gone is `unknown(reason=orphan)` |
| circular evidence — a pattern "confirmed" by claims it predicted | confirmation only from `evidence` rows of kind `specimen-pair` / `audit` / `oracle-compare`; a claim can never be an evidence id; checked by a constraint in the register script |
| double counting — a bit covered by two claims counts twice in coverage | inventory keeps "one class per cell, first match wins"; claims carry `n_bits` for ranking only, coverage comes from the cell partition |
| conflict hiding — two exact sources disagree and one silently wins | disagreement is a first-class status (`conflict`), shown as its own inventory line, never resolved by tier precedence |
| performance at ~4 x 10^7 die bits | no per-bit table; claims at pattern + scope (~10^4–10^5 rows); per-tile overrides are rows with one-tile scope; expansion in numpy |
| bureaucracy — every answer needs five fields filled by hand | the specimen tools write evidence + claims automatically from the pair (the design.toml already carries tool version, date, purpose); the register script derives tier from kind; hand-written rows are the exception (patterns), ~1 per law |
| vocabulary drift ("decoded", "partial", "table-only", "mixed") | the seven tiers + seven statuses are the only values; the register script dies on anything else |
| absence inflation — "never-exercised" used to make coverage over `shown_reachable` look complete | the tier needs an absence row with forced refusals and a corpus check; the die_bits ratio is always printed beside it; any image hit on the tier is a lift fault |

## 6. Adoption plan

### First step (DONE, commit b5e1dea13; kept as the original plan)

1. Add `evidence`, `claim_patterns`, `claims`, `claim_events` to `schema.py` (section 4; `lift_provenance` waits).
2. `scripts/claims_register.py --family cycloneiv`: full rebuild (delete + reinsert) from today's artefacts:
   - forced / M9K raw-diff JSONs -> `evidence(specimen-pair)`;
   - phys_map `*_tile` -> `measured` claims; class-wide `specimen` entries -> `pattern-predicted` (`class-generalise-v1`); voted maps -> `statistical`; LOCAL_LINE translation -> `pattern-predicted` (`ll-translate-v1`, parents = 4 LABs, scope = interior rows/columns only);
   - inventory classes -> claims with the tier from the mapping table in section 2 (1b `suspect`, LI band `conflict`).
3. Two queries as script subcommands: `by-pattern P`, `by-specimen S` (blast radius).
4. `cycloneiv_bit_inventory.py --record` reads tiers from `claims` instead of `LEDGER_TIER`; the ledger line gains the tier x status breakdown. Expect verified coverage to stay ~6.3 % and "evidence" to split into predicted / statistical / suspect / conflict.

### Can wait

- Automatic refute/confirm on specimen landing (the specimen tools write the event) — second session.
- Audit queue generator + the 10 % budget hook in `build_pool`.
- `lift_provenance` + the report line — after the Cyclone IV lifter uses `claims` as its lookup.
- PostgreSQL JSON operators; UI; MachXO2/ECP5 back-fill (their device-db is `vendor-decoded` with oracle gates already; register as one claim per tile type).

### What it would have caught earlier

| open item | how the model surfaces it |
|---|---|
| phys_map voted entries vs specimen exact | voted entries are `statistical/open` with an audit queue; the merge becomes supersession events; the "4/4 agree" check becomes 4 confirmations against ~2,900 unaudited, visible as a ratio instead of a sentence |
| ddb-vs-specimen LI band (6 class keys, 1,073 wrong) | both sources `suspect`, status `conflict`, 219 blocks listed by `by-pattern`; coverage drops for the LI band instead of counting under 2a/2b "evidence" |
| column coordinate anomaly (AFX != FX on 7 LAB columns; +1 after each M9K/DSP pair) | `afx-mirror-v1` has parents at interior LAB columns only; the 7 + 24 columns are outside `verified_scope`, so they are `pattern-predicted/open` with an audit queued BEFORE the 5,022-build sweep, not discovered by it decoding to nothing |
| 1b LE-used bit, 14/1,018 misses | the misses are refutation events; pattern `suspect`; the inventory shows 149,760 bits as suspect rather than "partial" |
| 2a counted as evidence while resting on vote peaks | weakest-link rule classes it `statistical`; the ceiling math in recovery-process.md would have been forced at the first ledger line |
