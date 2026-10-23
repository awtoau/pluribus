# Cyclone V interconnect ambiguity — root cause, and why it is NOT fixable with current data

Investigated: whether pluribus's already-imported routing-capacity tables
(`cv_route_muxes`/`cv_route_lines`/`cv_route_drivers`/`cv_p2r`/`cv_p2p`,
`scripts/cyclonev_db_import_routes.py`) can be used to resolve the ~54k
routing nodes per real design (DJI m2001, e50f) where Mistral's own decoder
reports "Source unknown" — i.e. a constraint-propagation / arc-consistency
pass over the candidate driver lists these tables already contain.

**Bottom line: no. This is a hard decode-failure, not a multi-candidate
ambiguity.** The capacity data cannot narrow these nodes because, for every
sampled case, NONE of a node's own candidate sources is consistent with the
raw configuration bits read from the bitstream — there is nothing to
eliminate down to one. Constraint propagation needs >=1 remaining valid
candidate to converge on; these nodes have zero.

## The mechanism (traced through Mistral's actual runtime decode)

`libmistral/cv-rmux.cc` resolves a routing mux's selected source in three
steps, not one:

1. `rmux_get_val(r)` reads the mux's declared CRAM bits (`pat.bits`,
   9-18 bits depending on pattern) into a raw integer `val`. This is a
   **physical mux select encoding**, not a binary index into the source
   list — real hardware muxes here use sparse/non-contiguous bit patterns
   (confirmed directly: pattern 7's legal values are
   `0x03,0x05,0x0a,0x0c,0x11,0x18,0x21,0x28,0x42,0x44,0x50,0x60` for 12
   slots — not `0..11`).
2. `rmux_get_slot(r)`: hashes `val` (`val % pat.hashdiv`) through a
   per-pattern table (`rmux_vhash`) to a candidate slot, then verifies
   `rmux_vals[slot] == val`. Fails (`slot = -1`) if the hash bucket is
   empty, or if it's occupied by a different legal value (collision).
   `rmux_vals`/`rmux_vhash` are the **complete catalogue of every legal
   raw encoding for that pattern** — not a sample.
3. `rmux_get_source(r)`: even if step 2 succeeds, the slot is then looked
   up in a **per-node-instance** forward/backward mapping
   (`sources_backward_mapping`, `ro_srcoff`/`ro_srclen` in the compiled
   binary) — the plain-text equivalent of this is each `data/<die>-r.txt.xz`
   line's own `SLOT:STYPE.x.y.z` tokens, already captured verbatim in
   `cv_route_muxes.sources` (JSON list of `{slot, type, x, y, z}`). If the
   hash-resolved slot number isn't one this specific node declares a source
   for, resolution still fails ("Source unknown" even though the shared
   per-pattern table matched).

`route_all_active_links()` (the function that prints "Source unknown on
rnode ...") only reaches that branch when ALL of the above already failed —
confirmed by reading the call site directly (`cv-rmux.cc:195-215`): the
warning path is the `else` of `if(snodei != 0xffffffff)`.

## What was tested

Real DJI m2001 firmware (read-only reference,
`/mnt/2tb/git/awto-dji/firmware/unpacked/C1_FW_V01.06.0000/m2001.depack.bin`,
die e50f / 5CEBA4U19C8), reproduced directly with Mistral's own tool:

```
mistral-cv routes2 5CEBA4U19C8 m2001.depack.bin   # 53,889 unresolved ACTIVE routes
mistral-cv decomp  5CEBA4U19C8 m2001.depack.bin out.bt 2>stderr.txt
                                                   # 386,648 "Source unknown" warnings total
```

The 386,648 figure is larger than 53,889 because `decomp`'s warning fires on
every rnode at a non-default value with no resolved source, including ones
that `route_all_active_links()`'s own `rnode_active()` frontier check would
not count as "active" for netlist purposes. 377,770 of the 386,648 parsed
cleanly for this analysis (rest had multi-line/edge formatting not needed
for the sample).

For every one of 377,770 real "Source unknown" cases, replicated steps 2+3
above in Python, using:
- `rmux_patterns`/`rmux_vals`/`rmux_vhash` read directly from
  `libmistral/cv-rpats.cc` (the runtime library's own compiled table,
  cross-checked byte-identical against `generator/routes.cc`'s copy —
  these are generator-input/runtime-output copies of the same data, not
  independent).
- `cv_route_muxes.sources` (already in `pluribus.db`, die e50f, 695,446
  rows — one per `data/e50f-r.txt.xz` line) for the per-node slot→source
  mapping (step 3).

Result, by outcome:

| outcome | count | % | meaning |
|---|---|---|---|
| `HASH_MISS` | 269,601 | 71.4% | raw value's hash bucket is empty — not any catalogued encoding |
| `COLLISION` | 89,382 | 23.7% | hash bucket occupied, but by a *different* legal value |
| `SLOT_NOT_IN_NODE_SOURCES` | 18,787 | 5.0% | value matches a legal encoding for the pattern, but this specific node doesn't declare a source at that slot |
| **resolvable via `cv_route_muxes` cross-reference** | **0** | **0%** | |

By dominant rnode type (the same four the task flagged — `GOUT`/`TD`/`H6`/`H3`
— confirmed as the real majority: 156,643 / 79,848 / 53,178 / 33,828 of
377,770, 85% combined):

| type | n | hash_miss | collision | slot_not_in_sources |
|---|---|---|---|---|
| GOUT | 156,643 | 115,726 | 40,905 | 12 |
| TD | 79,848 | 53,742 | 19,830 | 6,276 |
| H6 | 53,178 | 39,291 | 8,870 | 5,017 |
| H3 | 33,828 | 24,924 | 5,570 | 3,334 |
| V2 | 30,505 | 22,590 | 5,043 | 2,872 |
| V4 | 13,884 | 10,293 | 2,319 | 1,272 |

Spot-checked candidate-list size (`cv_route_muxes.sources` span, 2000-row
sample per type, not just the ambiguous subset): GOUT 34-35, H6/H3/V2/V4
4-13, TD 10-13. These are moderate, bounded candidate lists — not the
unconstrained case — but it does not matter: in every sampled failure, the
raw bits select **zero** of them, not two-or-more. There is no "pick the
right one of several plausible drivers" step available here for a
constraint-propagation pass to assist with.

## Why constraint propagation (the task's hypothesized fix) cannot help here

A CSP/arc-consistency narrowing pass earns its keep when a node has >=2
candidates consistent with available evidence and propagation removes all
but one. That requires the per-node decode itself to produce a *set* of
plausible candidates. It does not here: `rmux_get_source()` is not a
"narrow a candidate set" function, it's a **single deterministic lookup**
(hash the raw value, confirm, index into this node's own slot table) that
either succeeds with exactly one answer or fails outright. The failure mode
observed is uniformly "the raw bits don't decode to anything legal for this
node," never "the raw bits decode to 2+ legal answers." Cross-referencing
against other already-resolved nets (the task's proposed elimination
strategy) has nothing to operate on: there is no second candidate sitting
alongside the first to be eliminated by it.

## Is this an information-theoretic bitstream limit, or a Mistral coverage gap?

Genuinely open, and NOT the same question as "can pluribus fix this with
data already imported" (answered above: no). Two sub-possibilities, not
distinguished by this investigation:

1. **Mistral's fuzzing campaign never exercised these specific raw values**
   for these patterns (a coverage gap in `rmux_vals`/`rmux_vhash`, which are
   built from Mistral's own test corpus, not derived from first principles
   — see `cv-rpats.cc`'s provenance). If so, the *bits* may be fully
   decodable in principle, just not yet catalogued by anyone's fuzzing.
2. **The physical mux genuinely has more encodable states than are ever
   legally reachable** (padding, don't-care bit combinations, factory
   test modes) and these values are bits Quartus never programs for a
   real net — i.e. not actually ambiguous roultes at all, but mux
   instances this scan machinery miscounts as "active" when they're not.

Resolving which of these applies needs new ground truth pluribus does not
have: either Mistral's own upstream fuzzing campaign extended to cover more
raw values (their project, not this one), or a pluribus-run Quartus fuzzing
campaign exercising these specific `(pattern, rnode-type)` combinations
directly against known designs — the same approach already used for DSP
mode decode (`scripts/cyclonev_dsp_fuzz.py`) and flagged as real future work
in `docs/cyclonev-rust-port.md`. That campaign is NOT attempted here (out of
scope per the task) and is unrelated to the already-attempted FPLL fuzz
work (`scripts/cyclonev_fpll_fuzz.py`, issue #104).

## What's verified vs. assumed

**Verified directly (reproducible from this doc's commands):**
- 53,889 unresolved active routes / 386,648 "Source unknown" warnings on
  the real m2001 `.bt` decode, matching `docs/m2001-decomp-findings.md`
  (`awto-dji`) exactly.
- `rmux_patterns`/`rmux_vals`/`rmux_vhash` are byte-identical between
  `generator/routes.cc` (the fuzzer/table-generator's copy) and
  `libmistral/cv-rpats.cc` (the runtime library's compiled copy) — ruled
  out build/version skew as an explanation.
- `cv_route_muxes` (695,446 e50f rows, imported this session via
  `scripts/cyclonev_db_import_routes.py --die e50f`) exactly reproduces the
  per-node forward slot→source mapping that `data/e50f-r.txt.xz` encodes as
  plain text — this is the real, complete, already-captured candidate data
  the task asked to cross-reference.
- All 377,770 sampled "Source unknown" cases replicate Mistral's own
  hash/slot decode failure independently in Python using that data; 0
  cases newly resolve by cross-referencing `cv_route_muxes`.
- `GOUT`/`TD`/`H6`/`H3` are confirmed the dominant ambiguous types (85% of
  377,770 combined), matching the task's framing.

**Assumed / not independently verified:**
- Whether `rmux_vals`/`rmux_vhash`'s coverage gap (sub-possibility 1 above)
  reflects a genuine fuzzing-campaign limitation upstream in Mistral, vs.
  sub-possibility 2 (unreachable mux states) — not distinguished here,
  would need new ground truth (Quartus fuzzing) neither this session nor
  Mistral's existing data provides.
- Whether the same mechanism and proportions hold on dies other than e50f
  — only e50f was checked (the one die with a real design sample on hand).

## Verdict

**Not meaningfully improvable with data already in pluribus's database.**
No constraint-propagation pass was implemented, because the 0% resolution
rate on real sampled data shows there's nothing for one to converge on —
building it would not be a partial win worth shipping, it would resolve
nothing. The ~54k-per-design ambiguous-route gap is a real, hard limit of
the currently available Cyclone V routing model (Mistral's `.bt` decode +
its own capacity tables), not a pluribus integration gap. Lifting it needs
new ground truth (upstream Mistral fuzzing, or a pluribus-run Quartus
campaign), not better use of data pluribus already has.
