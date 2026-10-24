# Cyclone V FPLL fuzz — status

Issue: #104 (IP-recognition PoC, FPLL first). First step toward recognizing
instantiated vendor IP blocks instead of leaving them as flat gate soup —
no family has this capability yet.

Script: `scripts/cyclonev_fpll_fuzz.py`, sibling of `scripts/cyclonev_dsp_fuzz.py`.
Device: `5CEBA4U19C8` (e50f/e50b).
Flow: `quartus_map` -> `quartus_fit` -> `quartus_asm` -> `quartus_cpf -c` ->
`mistral-cv decomp`, same proven sequence as `cyclonev_dsp_fuzz.py`.

## Headline: the decode works for symmetric (50%-duty) M/N only

- All 6 compiled designs used 50% duty (`hi==lo`); asymmetric `hi != lo` counter fields are uncalibrated.
- `decode_fpll_tile()` reports `confidence=UNKNOWN` for those rather than guess a number.
- The decode has not been checked against any non-synthetic FPLL configuration.

## What field names mean — confirmed, not guessed

Mistral's `s FPLL.x.y:FIELD value` names (`M_CNT_HI_DIV_SETTING`,
`M_CNT_LO_DIV_SETTING`, `M_CNT_BYPASS_EN`, `N_CNT_*`, `CNT_PH_MUX_PRESET.<n>`)
are a literal, byte-for-byte match to Quartus's own
`<quartus>/libraries/megafunctions/altera_cyclonev_pll.v`
(`altera_cyclonev_pll_base` module) parameter names
(`pll_m_cnt_hi_div`, `pll_m_cnt_lo_div`, `pll_m_cnt_bypass_en`,
`pll_n_cnt_hi_div`, `pll_m_cnt_ph_mux_prst`, ...). Mistral has already
solved bit-extraction into named register fields; what was missing, and
what this fuzz run built, is the ARITHMETIC those fields encode.

## What DID work: M-counter divide, calibrated on 5 of 6 designs

`M_CNT_HI_DIV_SETTING == M_CNT_LO_DIV_SETTING == the fitted M multiply
factor` (hex-encoded decimal), for every in-VCO-range, 50%-duty design:

| Design | Requested (mult,div) | Fitted M_CNT_HI/LO_DIV | Decoded M | Match |
|---|---|---|---|---|
| `pll_m8_n1_c4` | (8,1) | 0x08 | 8 | OK |
| `pll_m20_n1_c7` | (20,1) | 0x14 | 20 | OK |
| `pll_m12_n1_ratio12` | (12,1) | 0x0c | 12 | OK |
| `pll_m16_n1_c4_ph` | (16,1), phase=625ps | 0x10 | 16 | OK |
| `pll_m16_n2_ratio8` | (16,2) | 0x08 | 8 | see below |
| `pll_m12_n3_c5` | (12,3) | 0x08 | 8 | see below |

`N_CNT_BYPASS_EN=1` (N divide-by-1) is directly confirmed on every design
above that requested `clk0_divide_by=1` via `altpll`. `M_CNT_BYPASS_EN=1`
(M divide-by-1) is NOT independently calibrated — no fuzzed design ever
bypassed M (`clk0_multiply_by` was never 1). Applying "bypass means
divide-by-1" to M is carried over from the N-counter's confirmed behaviour
and the general AN 661 bypass semantics, not confirmed against a compiled
M-bypass sample — flagged per-use, not silently assumed.

## Real finding: `clk0_multiply_by`/`clk0_divide_by` do NOT pass through
## literally — Quartus's PLL fitter normalises to its own absolute M/N

`pll_m16_n2_ratio8` (mult=16, div=2, net ratio 8) produced BYTE-IDENTICAL
FPLL config to `pll_m8_n1_c4` (mult=8, div=1, same ratio 8) — same
`M_CNT_HI/LO_DIV=0x08`, same `BYPASS_EN.5=1`. Two different user-requested
`(mult,div)` pairs expressing the same net ratio land on one physical
encoding; the fitter is free to pick whatever absolute M/N it likes for a
given ratio, not a literal pass-through of the two Verilog parameters.

`pll_m12_n3_c5` (mult=12, div=3, net ratio **4**) ALSO produced
`M_CNT_HI/LO_DIV=0x08` (ratio 8), not 0x04. No warning or error was
emitted by `quartus_map`/`quartus_fit`. Working theory, not independently
confirmed via a VCO-frequency report (none was available — see "What did
NOT work" below): ratio 4 at this design's 50MHz reference gives
VCO=2×4×50=400MHz, below Cyclone V's documented ~600MHz VCO minimum;
Quartus silently substituted ratio 8 (VCO=800MHz, in range) instead of
erroring. Confirmed independently as a real substitution, not a decode
bug, via the `pll_m16_n2_ratio8` control (same ratio 8, different
`(mult,div)` phrasing, same bytes).

**Practical implication**: decoding a REAL design's FPLL tile recovers the
fitted M/N ratio that ACTUALLY executes in hardware — which is the
correct and more useful target for RE anyway — but it cannot be checked
against a design's *source* `clk0_multiply_by`/`clk0_divide_by` values,
because Quartus itself does not preserve that literal mapping.

## What did NOT work / genuine gaps

- **No independent oracle for the fitted M/N ratio.** `cyclonev_dsp_fuzz.py`
  could cross-check its MODE decode against Quartus's own "DSP Usage
  Summary" in `.map.rpt`. No equivalent exists for PLLs in this install:
  the `.fit.rpt`'s own Table-of-Contents lists "17. PLL Usage Summary" but
  the section body is EMPTY (no `PLL Usage` text anywhere in the report) —
  this Quartus install is "SC Lite Edition" (`quartus-25.1`), which may
  omit detailed PLL/clock reports without an SDC clock constraint or a
  paid license tier. The only ground truth available was the `.bt` decompile
  itself, cross-checked by varying `(mult,div)` phrasing for the same ratio
  (the `pll_m16_n2_ratio8` control) rather than against a second
  Quartus-side report.
- **Non-50%-duty cases**: `clk0_duty_cycle=25` on the M=16/N=1(bypass)
  design was REJECTED outright by `quartus_fit`: `"PLL Output Counter
  parameter 'duty_cycle' is set to an illegal value of '25' ... '50' is a
  legal value"`. Not pursued further within this session's time budget —
  a different (mult,div) combination admitting an odd divide (needed for
  hi!=lo) would be required, not attempted.
- **Phase decode**: `clk0_phase_shift` is quantized, not an arbitrary ps
  value — `quartus_fit` rejected `5000ps` for the M=16 PLL with the legal
  set `{0, 156, 313, 469, 625, 781, 938, 1094} ps` (156.25ps granularity =
  1/8 of the 1250ps VCO period at VCO=800MHz, matching the 8
  `VCO_PH0_EN..VCO_PH7_EN` phase taps already visible in every tile's raw
  settings). One clean point confirmed: phase=625ps (4 steps, 180°) ->
  `CNT_PH_MUX_PRESET.5 = 4`, i.e. the preset value is literally the number
  of 156.25ps VCO-phase steps. Only ONE phase value was tested — this is a
  single data point, not a calibrated range; the formula is plausible
  (matches the legal-value list exactly) but NOT independently
  cross-checked against a second phase value.
- **C-counter (output divide, C0-C8) NOT decoded at all.** All 6 fuzzed
  designs used `altpll`'s default output counter (observed: always C5,
  `BYPASS_EN.5`/`CNT_IN_SRC.5`/`CNT_PH_MUX_PRESET.5`), and its
  `DPRIO0_CNT_HI_DIV.5`/`DPRIO0_CNT_LO_DIV.5` fields stayed at `00` in
  every design regardless of the requested ratio — meaning the C-counter's
  OWN divide value is encoded somewhere this fuzz run did not locate
  (`DPRIO0_CNT_*` looks like a dynamic-phase-reconfiguration shadow
  register, not the active counter config, based on the field name and
  its being always-zero here). `emit_fplls()`'s generated `altpll`
  therefore encodes the VCO-level M/N ratio only — it does NOT attempt a
  real per-output C-divide decode. Genuine gap, not hidden.
- **Bare-primitive cross-check (issue's cross-check #3): attempted, hit a
  Quartus Fitter internal crash, not resolved.** Directly instantiating
  `cyclonev_fractional_pll` (the atom underneath `altpll`, confirmed as a
  recognized WYSIWYG primitive name — not rejected at elaboration) via
  `cyclonev_pll_refclk_select` + manual `defparam`s on
  `pll_m_cnt_hi_div`/`pll_m_cnt_lo_div`/etc reached `quartus_map`
  successfully (0 errors) but `quartus_fit` crashed with an internal error:
  `Sub-system: TIS, File: tis_physical_timing_av_ffpll.cpp, Line: 771,
  "wrong delay unit"`. Most likely cause: the bare atom needs more of the
  ~60 auxiliary timing/delay parameters (`pll_cmp_buf_dly`,
  `pll_m_cnt_coarse_dly`, etc) set in a specific format that `altpll`'s
  megafunction wrapper fills in automatically and this minimal manual
  instantiation did not. **This independently confirms the issue's stated
  risk** — the megafunction wrapper is not a transparent pass-through; a
  bare-primitive calibration needs either the full parameter set correctly
  populated or a different (working) minimal atom wiring, neither
  attempted further given the session's time budget. Not treated as solved.

## Applying to another `.bt`

`--apply-real <decomp.bt>` decodes every FPLL tile in a given `.bt` and writes `tmp/cyclonev_fpll_fuzz/real_sample_report.json` (gitignored).
Per-tile `confidence=UNKNOWN` for any tile outside the calibrated cases (asymmetric counters, `M_CNT_HI==M_CNT_LO==0` without bypass).
`CNT_PH_MUX_PRESET` is reported raw, not decoded into degrees (phase-decode gap above).

## `emit_fplls()` in `verilog.py`

Confirmed no prior `emit_fpll`/`emit_pll` existed (grepped `verilog.py`
before writing — issue's claim verified, not assumed). New function,
same family as `emit_ebr` (hard-IP block emitter): prints a parameterized
`altpll` instance per tile in `data["fpll_tiles"]` with a confidence
comment, or a comment-only placeholder (no guessed parameter) for a tile
whose decode came back UNKNOWN.

**Integration depth**: standalone, tested against synthetic data
(resolvable + UNKNOWN tile shapes) and wired into `verilog.py`'s emission
`sections` list — but NOT plumbed through `cyclonev_lift.py` or `load.py`.
`data["fpll_tiles"]` is never populated by any current lifter
(`cyclonev_lift.py` does not model FPLL, confirmed in
`docs/cyclonev-lifter-status.md`'s "explicitly out of scope" list),
so `emit_fplls()` is a no-op (`return []`) on every real pipeline run
today, including the Hantek/MachXO2 regression (not MachXO2 anyway) and
any Cyclone V lift. This matches the task's own stated acceptable scope:
"fine to keep `emit_fplls()` as a tested, demonstrably-correct function
against synthetic data... if full pipeline plumbing is a lot of extra
work" — wiring `cyclonev_lift.py` to populate `fpll_tiles` from a tile's
raw `.bt` settings is real follow-on work, not attempted this session.

## Regression

- `python3 -m pytest tests/test_sqlite.py -q`: 8/8 pass, unaffected
  (`emit_fplls()` touches nothing SQLite-related).
- Full Hantek/MachXO2 `aw2-2d82auto` V07 pipeline, run from a sibling
  worktree at `/mnt/2tb/git/<repo>` depth (this worktree is nested too
  deep for `../../../awto-2000` to resolve): **pipeline passes, 0 errors,
  0 conflicting-driver, 0 loops.** Observed fabric counts:
  `2636/1280 (205%) LUTs, 1090 FFs, 4393 nets` — this does NOT match the
  documented baseline `2611/1280 (203%) LUTs, 1108 FFs, 4341 nets`
  (`docs/cyclonev-lifter-status.md`, `docs/cyclonev-blockmux-status.md`).
  **Confirmed this mismatch pre-exists this session's work**: checked out
  the commit immediately before this session's changes
  (`d0a8162fc`, before `scripts/cyclonev_fpll_fuzz.py`/`emit_fplls()`
  existed) and re-ran the same pipeline — identical
  `2636/1280 (205%) LUTs, 1090 FFs, 4393 nets`. The documented baseline
  was already stale on `main` before this session touched anything; this
  session's `verilog.py` change (a pure no-op addition gated on an absent
  key) cannot be the cause. Flagged here per the project's own mismatch
  convention (`docs/cyclonev-verification.md`); not investigated further
  — out of scope for issue #104, and not introduced by this work.

## Reproducing

```
python3 scripts/cyclonev_fpll_fuzz.py                       # all 6 designs
python3 scripts/cyclonev_fpll_fuzz.py --only pll_m8_n1_c4
python3 scripts/cyclonev_fpll_fuzz.py --skip-compile \
    --apply-real /path/to/decomp.bt                         # per-tile report
```

Output: `tmp/cyclonev_fpll_fuzz/mapping.json` (full settings per design),
`tmp/cyclonev_fpll_fuzz/<design>/<design>.bt` (raw Mistral decompile),
`tmp/cyclonev_fpll_fuzz/real_sample_report.json` (decode of the given `.bt`),
`tmp/logs/cyclonev_fpll_fuzz.log` (full run log). All under `tmp/`,
gitignored per project convention.

## Follow-on work

- Resolve the C-counter (output divide) encoding — needs designs that vary
  which Cx is used and its divide independently of M/N.
- Calibrate the odd-division (non-50%-duty) M/N case — needs a
  `(mult,div)` pair admitting an odd divide; `clk0_duty_cycle` alone
  cannot force it (rejected outright for the one case tried).
- Confirm the phase-step formula with a second value (currently one data
  point).
- Resolve the bare-primitive-vs-megafunction cross-check's Fitter crash —
  either populate the full `cyclonev_fractional_pll` parameter set or find
  a working minimal atom wiring.
- Wire `cyclonev_lift.py` to populate `data["fpll_tiles"]` from a real
  tile's settings so `emit_fplls()` runs against a real pipeline, not just
  synthetic data.
