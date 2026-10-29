# Provenance schema — generic claims / evidence / expectations for every family

Final design (phase B of #141). Supersedes section 4 of
[provenance-and-feedback.md](provenance-and-feedback.md) (the five-table sketch; the model in
sections 1–3 stands). Audit that motivated it: [schema-audit.md](schema-audit.md). Implemented
in `schema.py` (DDL), `provenance/` (vocabulary, scope expansion, queries, feedback, corpus),
`scripts/claims_register.py` (rebuild from artefacts), `scripts/framework_status.py`.

## Goals

- One object model for MachXO2, ECP5, Gowin, Anlogic, Cyclone IV, Cyclone V: keyed by
  `(family, device, space, subject_key)`; nothing Cyclone-shaped in a column name.
- **One database file per family / product / project, all from the same `schema.py`** (Dan,
  2026-10-29). Every tool and query works unchanged on any of them. `families` / `devices` hold
  only that file's rows; no table assumes another family is present; the done criterion and
  gate state of a family are read from its own file. Cross-DB questions ATTACH
  (`dbtools.open_many`, `dbtools.union`), never a foreign key across files. Layout:
  `databases/<family>/<name>.db` (databases/README.md); `PLURIBUS_SQLITE_PATH` selects one.
- Provenance as fine as the data allows: per object where an object was measured, per scope
  (pattern + region) where it was predicted, never "per class" when a finer row exists.
- Three things never confused: **measured / decoded** (a claim with a tier), **expected** (a
  prediction by a named pattern or matcher, not a claim), **seriously unknown** (no hypothesis).
- Blast radius in one query: what rests on evidence E, what pattern P predicts, what flips.
- Corpus = acceptance test; done = corpus 100 % with wrong = 0; the rest is parked, not deleted.
- Bulk without per-bit rows: scopes compress; numpy expands; per-object rows only as overrides.

## Vocabulary (closed; `provenance/tiers.py` dies on anything else)

- **space** (address space of a subject): `bit` (frame, v or device-native bit address),
  `tile-bit` (tile class + offset), `pip` (sink wire ← source wire), `mux-input` (block, group,
  input), `cell-param` (cell kind, parameter), `net-attr`, `stream-option`, `coord-map` (one
  coordinate system → another), `port-map` (hard-block port → wire).
- **tier** (fixed at creation): `measured`, `vendor-decoded`, `pattern-predicted`, `statistical`,
  `eliminated`, `never-exercised`, `unknown`.
- **status** (moves): `open`, `confirmed`, `verified-by-sampling`, `oracle-verified`, `suspect`,
  `refuted`, `superseded`, `conflict`, `parked`.
- **evidence kind**: `specimen-pair`, `vendor-decode`, `oracle-compare`, `audit`, `elimination`,
  `absence`, `image-hit`, `roundtrip`.
- **expectation status**: `open`, `confirmed`, `refuted`, `parked`.
- **unknown reason**: `unasked`, `unforceable`, `seen-in-image`, `orphan`, `conflict`,
  `not-required-by-corpus`.
- **scope kind**: `cells` (explicit list), `range` (frame × v box), `tile` (one tile +
  offsets), `tile-class` (column kind, x/y modulus + residues, ranges, offsets), `keys`
  (explicit subject keys, non-bit spaces), `formula` (expanded by a matcher), `all`.

## Tables (21 new; all additive; existing tables untouched)

Registry

| table | one line |
|---|---|
| `families` | vendor + family slug (`machxo2`, `ecp5`, `gowin`, `anlogic`, `cycloneiv`, `cyclonev`), LUT width, bit-address model, device-DB kind |
| `devices` | device per family: die, package list, `die_bits` (denominator), geometry JSON (frames, bits/frame, FX/VY tables or tile grid), vendor-DB reference |
| `address_spaces` | per family: which spaces exist and how a `subject_key` is spelled in each (the key grammar, as data) |

Objects (compressed)

| table | one line |
|---|---|
| `scopes` | a set of subjects: `(family, device, space, kind, definition JSON, n_objects, parent)`; the unit of claims, expectations, unknowns and audits; `definition` is expanded by `provenance/scopes.py` (numpy) — never stored per bit |

Evidence

| table | one line |
|---|---|
| `evidence` | one measurement / decode / compare / absence event: kind, family, device, `source_ref` (evidence file path or build names), optional `build_base`/`build_spec` → `corpus_builds`, generator script + version, tool version, `stable`, `result` JSON (raw diff, digest, absence record), `sha256` of the source file, commit |
| `evidence_scopes` | which scopes an evidence row touches (for "evidence intersects claim" without JSON scans) |

Patterns and matchers

| table | one line |
|---|---|
| `matchers` | a named pattern-matcher or statistical matcher: slug id, kind (`deterministic` / `statistical` / `llm-proposed`), version, code reference, parameters JSON, training-set evidence ids |
| `claim_patterns` | one law: slug id (`ll-translate-v1`), family, matcher id, law JSON (parameters), scope (where it applies), status, confirmations, refutations, verified_scope, created_commit; a changed law is a new id |
| `pattern_evidence` | (pattern, evidence, role `parent` / `confirm` / `refute`) |

Claims

| table | one line |
|---|---|
| `claims` | `(family, device, space, subject_key, scope)` → `meaning` JSON, `tier`, `status`, `pattern_id`, `n_objects`, `inventory_class`, `confidence_basis`, `created_commit`; unique on the key; most-specific scope wins at lookup |
| `claim_evidence` | (claim, evidence, role `direct` / `parent` / `confirm` / `refute`) — the weakest-link chain is walked through this + `pattern_evidence` |
| `claim_events` | append-only: claim or pattern, event, evidence, commit, ts, detail — nothing deletes |
| `claim_conflicts` | two claims on the same subject + overlapping scope that disagree: (a, b, status `open` / `adjudicated`, resolution, winner) — first-class, never settled by tier precedence |

Predictions and gaps

| table | one line |
|---|---|
| `expectations` | what a pattern/matcher PREDICTS for a scope: matcher, pattern, subject, scope, `expected` JSON, confidence, supporting evidence ids, status `open` / `confirmed` / `refuted` / `parked`, confirming evidence; never a claim until a specimen confirms it |
| `unknowns` | explicit gaps: scope, reason, `n_objects`, absence evidence (for `never-exercised`), status `open` / `parked` / `promoted`; "expected by" is a join to open expectations on the same scope |
| `audits` | sampling queue: pattern, claim or expectation, scope, priority, reason (`suspect` / `sampling` / `new-pattern` / `corpus-fail`), status, resulting evidence |

Lift and corpus

| table | one line |
|---|---|
| `lift_provenance` | per lifted object per bitstream: weakest tier + status among the claims used, claim ids |
| `corpus_members` | the acceptance set per family: name, kind (`oracle-build` / `third-party-image` / `roundtrip` / `lec`), device, build or manifest reference, sha256, `required` |
| `gate_runs` | one gate execution: family, script, commit, code stamp, params, passed, summary |
| `gate_results` | per (run, member, category): matched / missing / extra / wrong, headline, passed, `failing_claims` (claim ids under the failing cone via lift_provenance) |
| `done_criteria` | per family: the criterion as data, state (`open` / `met`), the gate run that met it, commit |
| `coverage_ledger` | tier × status × class × commit rows, from real data only (replaces `LEDGER_TIER` in the inventory script) |

## Representation of bulk

- Cyclone IV has 39.4 M die bits; MachXO2-1200 ~0.6 M; ECP5-85F ~37 M. No per-bit table.
- A **scope row** is the unit. Expansion: `provenance.scopes.expand(scope, geom) -> np.ndarray`
  of flat indices (`frame * bits_per_frame + v`) for bit-space scopes; key lists for others.
- **Overrides**: a per-tile measured claim is a claim whose scope has kind `tile` (one tile +
  offsets); lookup takes the most specific scope (`tile` > `tile-class` > `range` > `all`).
- **Partition for coverage**: one class per bit, first match wins — unchanged from the inventory;
  `coverage_ledger` rows come from the partition, `claims.n_objects` is for ranking only.
- `scopes.n_objects` is written by the register from the expansion, never by hand.

## Three states, how represented, how queried

| state | representation | query |
|---|---|---|
| measured / vendor-decoded / … | `claims` row with that tier; evidence linked in `claim_evidence` | `claims WHERE tier=? AND status NOT IN (refuted, superseded)` |
| expected by pattern P / matcher M | `expectations` row (status open) citing `pattern_id` / `matcher_id`; NO claims row | `expectations WHERE status='open'`; "what does P predict" = `WHERE pattern_id=P` |
| seriously unknown | `unknowns` row with reason, NO open expectation on an intersecting scope | `unknowns LEFT JOIN expectations ON same scope WHERE expectations.id IS NULL` (`queries.seriously_unknown`) |
| never-exercised | `unknowns` row with `absence_evidence_id` set + a `claims` row tier `never-exercised` | `claims WHERE tier='never-exercised'` |
| parked (not required by corpus) | `unknowns.status='parked'` / `expectations.status='parked'`, reason `not-required-by-corpus`; rows kept | `queries.parked(family)` |

Weakest link: `provenance.tiers.weakest(chain)`; a claim's effective tier =
`min(own tier, tier of every claim its pattern's parents rest on)` with the order
`measured > vendor-decoded > eliminated > pattern-predicted > statistical > never-exercised > unknown`.

## Blast-radius queries (`provenance/queries.py`, SQLAlchemy Core)

| function | question |
|---|---|
| `by_pattern(conn, pattern_id)` | every claim and expectation predicted by P, with Σ n_objects |
| `by_matcher(conn, matcher_id)` | every expectation and pattern produced by matcher M (any version) |
| `resting_on(conn, evidence_id)` | claims citing E directly + claims of every pattern whose parents include E + expectations supported by E |
| `flips_if_wrong(conn, evidence_id)` | `resting_on` grouped by pattern with Σ n_objects, plus `lift_provenance` rows citing those claims (netlist impact per bitstream) |
| `open_expectations(conn, family, limit)` | open expectations ranked by n_objects |
| `coverage(conn, family, device, commit=None)` | tier × status × inventory_class → Σ n_objects (what the ledger records) |
| `corpus_state(conn, family)` | last gate run per member, pass/fail, headline, wrong |
| `done_state(conn, family)` | done_criteria row + whether the last run meets it |
| `seriously_unknown(conn, family)` | unknowns with no open expectation on an intersecting scope |
| `audit_queue(conn, family, limit)` | queued audits by priority |
| `conflicts(conn, family)` | open claim_conflicts with both sides |

## Feedback (`provenance/feedback.py`)

- `refute(conn, claim_id, evidence_id, commit)`: claim → `refuted`; its pattern → `suspect`;
  every other claim citing the pattern → `suspect`; audits queued (reason `suspect`) for the
  pattern's other scopes, priority = n_objects; expectations of the pattern → stay `open` but
  the pattern status is visible on them; every step one `claim_events` row.
- `confirm(conn, claim_id, evidence_id, commit)`: confirmations += 1, event; pattern graduation
  to `verified-by-sampling` by the N rule (3 for 1-D, 5 for 2-D laws, from `law.dims`).
- `confirm_expectation(conn, expectation_id, evidence_id, commit)`: creates the `measured` claim
  (scope = the evidence's scope), links evidence, marks the expectation `confirmed`; the
  pattern gets a `confirm` row.
- `refute_expectation(...)`: expectation `refuted`; pattern `suspect`; siblings' audits queued.
- `conflict(conn, claim_a, claim_b, commit)`: both `conflict`, a `claim_conflicts` row.
- `supersede(conn, old, new, commit)`: statistical → exact replacement rule.

## Corpus and done criterion (`provenance/corpus.py`)

- A gate script ingests its result through `record_gate_run(family, script, commit, stamp,
  results)`: one `gate_runs` + one `gate_results` row per (member, category); headline =
  matched / (matched + missing + extra + wrong); member passes iff headline == 100 % AND
  wrong == 0 across its categories (missing and extra counted in the headline).
- `evaluate_done(family, run)`: met iff every `required` member has a result in this run and
  passes. On met: open unknowns / expectations of that family → `parked`, reason
  `not-required-by-corpus`, `claim_events(parked)` per row, `done_criteria.state='met'`.
- On a later failure: members that fail name their failing cone (`lift_provenance.claim_ids`
  of the mismatching objects); exactly those claims → `suspect`, their patterns → `suspect`,
  their parked unknowns / expectations → `open` again, audits queued with reason `corpus-fail`;
  `done_criteria.state='open'`. Nothing is deleted at any step.
- Headline per category per the scoring-faults rules; fusion vs split stay in the per-run
  summary JSON, not folded into one number.

## Mapping existing artefacts → rows (what `claims_register.py` does)

| artefact | rows |
|---|---|
| `evidence/cycloneiv/cycloneiv_forced_*.json` (LOCAL_LINE pairs, 4 LABs; tier tables; gxnb) | one `evidence(specimen-pair)` per pair; per-tile `measured` claims (space `bit`, scope `tile`) for each hop's bits; `claim_patterns(ll-translate-v1)` parents = the 4 LAB sets; `expectations` for the other 9,356 LABs (scope `tile-class`, interior rows/columns only); edge rows/M9K-adjacent columns → `unknowns(unasked)` |
| `evidence/cycloneiv/cycloneiv_m9k_*.json` (site M9K_X23_Y40_N0) | `evidence(specimen-pair)` per pair; `measured` claims for the per-width init maps (`map1/2/4/8/9/16` → space `cell-param`, subject `M9K:init:w<width>:<index>`, scope `tile` of the one site); random round-trips + 120/120 held-out → `confirm` events; `claim_patterns(m9k-init-x1-law-v1)` fitted from map1 → `expectations` for other M9K sites (never `measured`); x18/x32/x36 → `unknowns(unasked)`; hardware (word,bit) → cell for widths > 1 → `unknowns(unasked)` |
| `tmp/ddb/stingray4_blockmap.npz` | one `vendor-decoded` claim per block via `claim_patterns(ddb-group-eq-edge-v1)` |
| (retired #165) phys_map / li_map / afx-mirror claims | removed with the coordinate model, see `docs/cycloneiv-retired-coordinate-model.md` |
| inventory classes 1a–6 | one claim or unknown per class with the tier from provenance-and-feedback.md §2 (1a `pattern-predicted`/`oracle-verified`; 1b `suspect`; 1c `statistical`; 2a/2b retired (#165); 3 see above; 4a–4e, 5c, 6 `unknowns`); `n_objects` from the live inventory JSON when present, else from the last ledger line |
| `docs/cycloneiv-corpus.md` manifest (`scripts/cycloneiv_corpus_fetch.py`) | `corpus_members(kind=third-party-image, required=false)` + `evidence(image-hit)` per decoded image |
| MachXO2 / ECP5 device-db tile types | one `vendor-decoded` claim per tile type (space `tile-bit`, scope `tile-class`), status `oracle-verified` where the gate covers the type; corpus members from `scripts/machxo2_gate.py` sets and `tests/baselines/ecp5_oracle.json` targets; gate_results from the baseline JSON |
| Gowin | corpus members from `scripts/gowin_lec.py` designs (kind `lec`); chipdb → `vendor-decoded` claims per tile type |
| Cyclone V | `corpus_builds` ok rows → corpus members; `gate_verdicts` verdicts → gate_results when present |

## Lookup cost

- Claims per family ~10^4–10^5; register loads them once per lift into a dict keyed by
  `(space, subject_key)` → list of (scope, claim) sorted most-specific first.
- `scopes.expand` for a `tile-class` scope over 9,360 LABs × 305 offsets = 2.9 M indices in
  ~50 ms (numpy broadcast); the inventory does the same today.

## Per-database shape (what changed from the shared-DB sketch)

- The §4 sketch and the audit's "every DB holds one device" finding assumed one shared DB;
  one device per file is now the intended shape.
- `families` is a per-file registry (typically one row); `coverage_ledger`, `done_criteria`,
  `gate_runs` are per file. `framework_status.py --db <path>` reads one; `--all` walks
  `databases/**/*.db` and prints each file's state side by side (`dbtools.kept()`).
- `claims_register.py --family F` writes into the file `PLURIBUS_SQLITE_PATH` names; it
  refuses to register a family into a file whose `families` row is a different family.
- Nothing in `provenance/` joins across files; the one cross-DB example is
  `dbtools.claims_by_tier_all()`.

## Not in this design

- Migration of existing tables (audit proposal items 1–10 need Dan's go).
- Postgres JSON operators; everything goes through link tables so both dialects work.
- UI.
