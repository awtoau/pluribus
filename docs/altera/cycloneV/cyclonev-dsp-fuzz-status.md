# Cyclone V DSP mode fuzz — status

Ground-truth mapping of Quartus DSP operations to Mistral's decompiled
`DSP.*` settings. Follow-on to `docs/altera/cycloneV/cyclonev-lifter-status.md`'s explicit
gap: Mistral itself does not decode DSP mux usage/port mapping ("TODO:
everything" in its own source) — this maps MODE strings to known operations
by compiling designs where the operation is controlled, not assumed.

Script: `scripts/cyclonev_dsp_fuzz.py`. Device: `5CEBA4U19C8` (e50f/e50b).
Flow: `quartus_map` -> `quartus_fit`
-> `quartus_asm` -> `quartus_cpf -c` -> `mistral-cv decomp`, same proven
sequence as `scripts/cyclonev_die_probe.py`.

## Confirmed: pure-multiplier modes (high confidence)

| Design | Verilog | Quartus DSP Usage Summary | Mistral `DSP.*:MODE` |
|---|---|---|---|
| `mult9x9` | `a * b`, 9-bit signed inputs, registered | "Independent 9x9" | `M9X9` (explicit) |
| `mult18x18` | `a * b`, 18-bit signed inputs, registered | "Two Independent 18x18" | *(none — see below)* |
| `mult27x27` | `a * b`, 27-bit signed inputs, registered | "Independent 27x27" | `M27X27` (explicit) |

- 27x27 fits in ONE DSP block directly on e50f — no multi-block ganging
  needed, contrary to the task's "if it needs multiple blocks" caveat.
- One DSP tile per design, confirmed by grepping the full `.bt` (no second
  tile shows any `s DSP` line) — each design genuinely used exactly one
  block, so the MODE attribution isn't confounded by a second configured
  tile.
- `M9X9`/`M27X27` confidence: HIGH. Both the Quartus synthesis report (an
  independent oracle on what operation was built) and Mistral's own named
  `MODE` string agree, for a design whose behaviour is fully known (we wrote
  it).

## M18X18 is encoded as the chip's default (no explicit MODE line) — confidence: MEDIUM-HIGH

- `mult18x18` has NO `MODE=...` line at all in the decompile, despite
  Quartus's own report confirming a DSP block did the multiply ("Two
  Independent 18x18"). Mistral only prints an `s` line for a field that
  differs from its default/zero encoding — so this is consistent with
  M18X18 (or "two independent 18x18", Quartus's own name for the mode) being
  the all-zero default `MODE` field value, not an unmapped case.
  - Not independently confirmed from a second angle (e.g. the Mistral source
    enum order) — flagged MEDIUM-HIGH, not HIGH, because the only evidence
    is "absence of an override line", not an explicit default-value readout.
  - `multacc18x18` (below) reproduces the same absence under the same
    underlying operation, which is corroborating but not independent
    evidence (same DSP configuration, different soft-logic wrapper).

## multacc18x18 — NEGATIVE RESULT, not a confirmed accumulate-mode mapping

Design: `acc <= acc + (a * b)`, 18x18 signed multiply into a registered
accumulator, intended to force a DSP-internal accumulate/systolic mode.

**Did not exercise DSP-internal accumulate.** Quartus's own DSP Block Usage
Summary for this design says "Two Independent 18x18" — identical to the
plain `mult18x18` design. 44 ALUTs + 44 dedicated registers appear in the
synthesis report: Quartus built the accumulator in soft fabric logic and
used the DSP block only for a plain 18x18 multiply. The Mistral decompile is
correspondingly almost identical to `mult18x18`'s (diff below), confirming
this at the bitstream level too — it is not a synthesis-report-only claim.

```
Settings present in mult18x18 but NOT multacc18x18:
  CLK_AX17_SEL, CLK_AYZ17_SEL, CLK_BX17_SEL, CLK_BYZ17_SEL,
  CLK_DYN_CTRL_SEL, OREG_CTRL=REG

Settings present in multacc18x18 but NOT mult18x18:
  CLK0_SEL
```

- This diff is real and reproducible, but its semantic meaning (register
  bank selection differences from soft-logic register placement around the
  DSP block, vs anything DSP-internal) is NOT established — do not treat it
  as an accumulate-mode signature.
- Tried forcing the real DSP-internal accumulate path via the
  `altmult_accum` megafunction instead of inferred Verilog. Quartus
  rejected it outright: `Error (272006): Cannot use ALTMULT_ACCUM wrapper
  with Cyclone V device family`. ALTMULT_ACCUM is a legacy (pre-Arria-era)
  megafunction not supported on this family at all — itself a real, useful
  negative finding for anyone else trying this path.
- `altera_mult_add` (the modern replacement IP, confirmed present in this
  Quartus install's megafunction library) does expose `accum_sload`/
  `sload_accum` parameters that look like the right lever, but its full
  parameter surface is large and undocumented defaults made it unlikely to
  succeed within this session's remaining time — not attempted further.
  Follow-on work, not a dead end.

## 18x19 combined, systolic FIR, complex multiply — NOT attempted

Mode names such as `M18X19_COMBINED` and the task's scope list (18x18 complex multiplier, systolic FIR): none of
these were tried this session. Time went to nailing the pure-multiplier
modes solidly plus one real (negative) accumulate-mode attempt, per the
task's stated priority order.

## What's left for a follow-on session

- Accumulate/systolic MAC mode: retry via `altera_mult_add` with
  `accum_sload`/`sload_accum` set explicitly, or via the Quartus IP
  Catalog/`qmegawiz` GUI-equivalent flow instead of a raw `defparam`
  instantiation (the IP catalog may pick parameter combinations that compile
  cleanly where a hand-guessed `defparam` set does not).
- 18x18 complex multiplier mode (`M18X19_COMBINED`-style) — not attempted.
- Any mode requiring >1 DSP block (ganged wide multiply) if one exists on
  e50f — 27x27 turned out not to need this, so no ganged-block case has
  been exercised yet at all.
- M10K block-RAM contents — explicitly out of scope for this task, listed
  in `docs/altera/cycloneV/cyclonev-lifter-status.md` as a separate follow-on.
- LAB-common-logic and peripheral mux decoding — separate follow-on, not
  touched.
- No lifter integration attempted (`lifters/cyclonev_lift.py` has no DSP
  handling added). Per the task's own framing, a verified mapping + status
  doc without integration is a complete deliverable on its own; the
  multiplier-mode table above is solid enough to eventually back a "this
  DSP tile is doing an NxN signed multiply" annotation, but the accumulate
  case needs the follow-on work above before any lifter code should claim
  to resolve MAC/systolic configs.

## Reproducing

```
python3 scripts/cyclonev_dsp_fuzz.py              # all 4 designs
python3 scripts/cyclonev_dsp_fuzz.py --only mult9x9
```

Output: `tmp/cyclonev_dsp_fuzz/mapping.json` (full settings per design),
`tmp/cyclonev_dsp_fuzz/<design>/<design>.bt` (raw Mistral decompile),
`tmp/logs/cyclonev_dsp_fuzz.log` (full run log). All under `tmp/`,
gitignored per project convention.
