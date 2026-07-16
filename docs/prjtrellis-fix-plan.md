# prjtrellis fix plan — restore decoder trust before resuming vendor-stream RE

**Hard gate:** no further RE conclusions about the target vendor stream until the
decoder is fixed and *verified complete*. We discovered the decoder silently
drops ~half of a real vendor stream (the `0x72` lenient-truncation bug), so any
analysis built on the old `.config` is suspect. Fix → re-decode → verify →
*then* resume.

## Why this exists

Two independent agent reviews + byte-decodes of the real vendor bitstreams found
the decoder we rely on (prjtrellis pytrellis/ecpunpack) is the single load-bearing,
unversioned, actively-wrong dependency. It is patched only as uncommitted edits in
a `debris/tmp` tree, and its worst bug (`0x72`) makes a truncated decode look
complete. Full finding list: `tmp/prjtrellis_issues.md` (9 code issues, A–I).

## Status (done)

- **Clone** of prjtrellis (a local checkout) — `origin`=our fork,
  `upstream`=YosysHQ, `database` submodule populated.
- **NoGIL fixed (issue D):** pybind11 2.11→2.13.6 + `py::mod_gil_not_used()`;
  pytrellis now imports + decodes under **python3.14t** (GIL disabled). Build:
  `libtrellis/build_ft`, `cmake -DPython3_EXECUTABLE=python3.14t`.

## Decision: PORT the decoder to Python (native), validated exhaustively

Doing the C++ parser fix *and* a later port is doing the work twice. We port now.
Rationale (see also `docs/native-decoder-direction.md`): it collapses decode+lift
into one relational pipeline, kills the text-interchange + regex-reparse + pybind
boundary + black-box-trust problem, makes every bug we found (0x72, truncation,
completeness) impossible by construction, gives per-bit provenance, and is generic
(family-as-data). NoGIL parallelises the tile decode.

**The C++ NoGIL build is NOT discarded — it is the fidelity reference.** Now that
pytrellis runs under python3.14t, the Python decoder is tested against it in-process.

**Incremental, testable order (nothing thrown away between steps):**
1. **Parser** (bin → CRAM frames + command stream). Small; where all our bugs are.
   First milestone: **byte-exact round-trip** (bin→frames→bin) on a real vendor
   stream — the proof prjtrellis fails.
2. **Tile decode** (CRAM → enums/words/arcs via DB-loaded `bits.db`). The
   parallelisable, SQL-joinable bulk. Validated by parity vs prjtrellis `.config`.
3. **Routing graph** (for lift net-globalisation). Hardest; deferred — until then
   the lifter keeps using pytrellis for `get_routing_graph` only.

**Completeness testing is exhaustive — do NOT optimise coverage.** All loops, all
targets:
- **#3 re-encode** (decoder lossless): bin→decode→re-encode→bin byte-exact, every bitstream.
- **#1 corpus equivalence** (lifter): recovered.v ≡ original fuzz.v via yosys, all ~3000 targets (no Diamond re-run); hard-IP targets compared by config enums.
- **#2 Diamond round-trip** (vendor-grade): lift→Verilog(+constraints)→Diamond→bin′, structural bit-diff (residual = quality metric).
- **parity**: Python decode == prjtrellis decode (semantic) across the whole corpus.

The 9 C++ issues (A–I) are still filed/​upstreamable to the fork, but they are the
*reference's* bugs — our decoder fixes them by construction, so they are no longer
our critical path.

## Phased plan

### Phase 0 — baseline (before touching parser logic)
- Build the untouched clone; decode the vendor streams + a fuzz sample; snapshot the
  `.config`s as the "pre-fix" regression baseline (so every later change is diffable).

### Phase 1 — parser correctness (the core; all in the clone's C++)
Order by dependency:
1. **A — completeness flag + fail-loud.** Add `truncated`/`stop_offset`/`stop_cmd`
   to `Chip`, expose via PyTrellis; default to fail-loud; only continue past an
   unknown command with explicit evidence the final-frame CRC passed.
2. **B — command `0x72`.** Characterize its length via Diamond oracle (build
   bitstreams toggling one sysCONFIG/EFB feature, byte-diff the post-frame region),
   add a consuming case so the parser continues into the modelled EBR/USERCODE/DONE
   tail — recovering the vendor stream's lost `.bram_init`.
3. **C — forced-device geometry check.** Assert read frame-count == forced device's
   frame-count; error on mismatch (kills the wrong-device silent truncation).
4. **F/G/H/I** (independent, parallel): frame_count bounds + zero-case; assert→
   `BitstreamParseError` bounds checks; `chip->` null-checks; SPI_MODE → parse error.

### Phase 2 — verification harness (issue E)
Decode-completeness regression, run on the vendor streams + corpus:
- no lenient/truncated stop; `frames_read == num_frames`; final CRC verified;
  the vendor stream yields its 6 `.bram_init` sections; byte-exact `read→deserialise→serialise→
  write` round-trip; wrong-device decode errors instead of truncating.
Wire it into the fork's CI (currently packaging-only) and mirror a completeness
assertion into pluribus `scripts/re_assertions.py`.

### Phase 3 — DB-encoding fixes (pluribus#29; needs Phase 1 so EFB even decodes)
EBR.MODE F1B33/34 (not F1B35); DP8KC↔PDPW8KC differentiator; PULLMODE/BASE_TYPE
overlap; CIB F24–F27; complete `109-efb` fuzzer + `check.py`. Each verified by the
bidirectional `check_enum_setting` against Diamond. **Enhancement:** stamp the
Diamond version into every fuzz result and support cross-version diffing — the
skew map *is* the vendor-error detector, and likely explains some "bugs" here.

### Phase 4 — re-decode everything
Repoint pluribus `TRELLIS_*` at the clean clone; re-run the full decode (vendor
streams + corpus). Diff vs the pre-fix baseline; quantify what changed (especially
the newly-recovered vendor EBR contents). This is the "run all the trellis code
again with this fixed" step.

### Phase 5 — fork hygiene + publish (APPROVAL GATE — public)
Considered commits on the fork (device-forcing corrected, `0x72` handling,
completeness flag, fuzzer check-suite); file issues A–I; push to `awtoau/prjtrellis`.
Requires explicit approval of exact public content.

### Then — resume vendor stream RE
On the verified-complete decode: the SPI ident, the recovered EBR/peripheral
contents, the EFB path — the work that was blocked by the invisible config.

## Parallel (non-blocking) pipeline hygiene the inventory flagged
`db.py` default backend postgres vs CLAUDE.md sqlite; `psycopg2` import in
`tools/run_machxo2_fuzz.py`; `requirements.txt` covers 2/7 deps; hardcoded absolute
paths in `re_assertions.py`; absent `aw21.sty`. Fix opportunistically; not on the
critical path.
