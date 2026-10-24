# Cyclone V verification harness

One command that re-derives every Mistral-dependent claim this project makes
about Cyclone V, from scratch, against whatever Quartus install is on this
machine right now, and checks the result against the numbers already
published in `docs/cyclonev-lifter-status.md` / `docs/cyclonev-dsp-fuzz-status.md`.

Script: `scripts/cyclonev_verify_all.py`. Log: `tmp/logs/cyclonev_verify_all.log`.

## What it verifies

| Stage | Reuses | Checks against |
|---|---|---|
| Die probe | `scripts/cyclonev_die_probe.py: compile_die()` | all 7 Mistral-covered dies compile |
| DSP fuzz | `scripts/cyclonev_dsp_fuzz.py: quartus_compile_design()` / `decompile_and_extract_design()` | `docs/cyclonev-dsp-fuzz-status.md`'s MODE mapping (`mult9x9`->`M9X9`, `mult27x27`->`M27X27`, `mult18x18`/`multacc18x18`->no explicit MODE, the documented default-encoding result) |
| Lifter selftest | `lifters/cyclonev_lift.py: CycloneVLift` directly | `docs/cyclonev-lifter-status.md`'s LUT/FF/net/arc/unparsed-line counts (61/64/139/608/0 on corpus design `regbank16`) |
| pad_map DB insert | `load.py: load_cyclonev()` (real subprocess) | the lifter selftest's own pin-recovery ground truth (19 annotated, 0 duplicate pins on `regbank16`) |

None of the four stages are copy-pasted logic — each imports and calls the
existing script's own functions. Nothing here is a second implementation
that could drift from the one actually used elsewhere.

## Re-running against a different Quartus install

```
PLURIBUS_QUARTUS_BIN=/path/to/quartus-24.1/quartus/bin \
  python3.15t scripts/cyclonev_verify_all.py
```

With no override, `scripts/toolchain.py:quartus_bin()` globs the
conventional install locations and picks the newest version-sorted match —
a Quartus upgrade on this machine is picked up automatically, no code
change. `PLURIBUS_MISTRAL_CV` overrides the Mistral binary the same way.

Fast re-check without the two Quartus stages (useful when only the lifter
or `load.py` changed, not when checking a different Quartus install):

```
python3.15t scripts/cyclonev_verify_all.py --skip-die-probe --skip-dsp-fuzz
```

## What a mismatch means

Every check logs one line either way:

```
DSP mode mult9x9: previously M9X9, now: M9X9 — OK
DSP mode mult18x18: previously None, now: M18X18 — MISMATCH, investigate
```

A mismatch is not automatically "the new Quartus version is wrong" — it is
a real divergence between what this project has published and what the
toolchain now produces, and the direction of the error is unknown until
investigated. In particular:

- **A die-identification mismatch (rbf size, header signature) is a
  serious finding**, not a log line to shrug off. Die identification by
  `.rbf` size assumes sizes are stable across Quartus versions; if the sizes for a die change, something about the compile
  flow or the device's own config-RAM accounting changed, and every size
  comparison done against the old numbers needs re-checking before being
  trusted again. Treat it as its own investigation, not a line item.
- A DSP mode mismatch could mean Quartus's own default encoding changed
  between versions (plausible — `mult18x18`'s mapping is already flagged
  MEDIUM-HIGH confidence specifically *because* it rests on "no override
  line" rather than an explicit readout), or that this harness's own
  comparison logic has a bug. Check the raw `.bt` before assuming either.
- A lifter selftest count mismatch against the SAME reference `.bt` file
  means `lifters/cyclonev_lift.py` changed behaviour — expected after a
  deliberate lifter change, a red flag otherwise.
- A pad_map count mismatch against the SAME reference `.bt` means
  `load.py`'s `load_cyclonev()` pad insert changed behaviour — same as
  above.

The harness does not auto-update the documented expected values
(`EXPECTED_LIFTER`/`EXPECTED_PADMAP`/`EXPECTED_DSP_MODE` constants in
`scripts/cyclonev_verify_all.py`) on a mismatch. Updating them is a
deliberate decision once the mismatch is understood, not something to do
reflexively to make the harness pass again.

## Threading

Producer/consumer, not a flat worker pool. The slow, CPU-bound part is the
Quartus compile sequence (`quartus_map` -> `fit` -> `asm` -> `cpf`); the
Mistral decompile + comparison step is much cheaper per item. A flat pool
where each thread does compile-then-decompile-then-next-item in lockstep
wastes cores: a thread sits idle decompiling while other cores could
already be compiling the next design.

- **Producer pool**: `os.cpu_count()` threads (detected, never hardcoded),
  each running one full Quartus compile sequence per work item (one die,
  one DSP design), pulling the next item off a shared `queue.Queue` the
  moment it finishes its own.
- **Consumer pool**: a small fixed pool (`--decompile-workers`, default 4)
  draining a second `queue.Queue` of completed compiles as they land.
- Same `threading.Thread` + `queue.Queue` primitives `reach.py` uses for
  its BFS worker pool. Confirmed free-threaded at runtime the same way
  `reach.py` does: a `NoGIL: True/False` line from `sys._is_gil_enabled()`
  at startup, not assumed from the `python3.15t` invocation.

The lifter selftest and pad_map stages are single-shot (not Quartus-bound,
nothing to parallelise) and run outside the producer/consumer pools.
