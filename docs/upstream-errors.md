# Upstream errors and gaps found by pluribus

A register of defects, gaps and documentation errors found in **other people's**
work: prjtrellis, yosys, nextpnr, Lattice Diamond, apicula.

This is deliberately separate from [`upstream-contributions.md`](upstream-contributions.md),
which is MachXO2-specific and tracks *what we could contribute*. This file tracks
*what we found wrong*, across every project and family, whether or not we intend to
submit anything.

**Why a register at all.** These findings were scattered across a dozen issues, and
an RE project's most expensive mistake is re-trusting a source that has already
been shown wrong. Two findings here were re-derived after being forgotten once.

**Submission status.** Project policy is not to push to upstream remotes, and
filing on public repositories is gated on explicit approval, so the default state
of everything below is **documented, unsubmitted**. That is a deliberate choice,
not neglect.

## Classification

| tag | meaning |
|---|---|
| **DEFECT** | upstream is wrong — it produces an incorrect result |
| **GAP** | upstream is incomplete — it produces no result where one exists |
| **DOC-WRONG** | vendor documentation contradicts the vendor's own tools |
| **OPEN** | anomaly we found but have not explained; may be ours |

Distinguishing DEFECT from GAP matters: a gap fails loudly and is safe, while a
defect produces a plausible wrong answer. Only the second class can silently
corrupt a recovered netlist.

---

## prjtrellis

### DEFECT — decoder truncates at command 0x72
The stock decoder stops at the undocumented `0x72` command (present when the EFB
is active), silently dropping the post-frame configuration including real EBR
block-RAM initialisation. Not an error — a short read that looks complete.

Our native Python decoder makes this impossible by construction, and
`scripts/native_bitstream_roundtrip.py` check [3] exists specifically to prove the
EFB blocks and EBR writes survive a round-trip. Tracked around #31/#34.

### DEFECT — degenerate enum encodings (under-fuzzed I/O standards)
`PIOA.BASE_TYPE` holds 84 values in several ECP5 tiles that resolve to only 3
distinct bit patterns, so those standards are indistinguishable in any bitstream.
Measured per tile with `scripts/enum_degeneracy.py` (#85):

```
PICL1, PICL1_DQS0    84 values -> 28 encodings  (33%)
PICT0                40 values ->  3 encodings  ( 8%)
PICT1                40 values ->  2 encodings  ( 5%)
PICL0, PICL0_DQS2    84 values ->  3 encodings  ( 4%)   <- 30 values share one
PICR0, PICR0_DQS2    84 values ->  3 encodings  ( 4%)
```

A 9.3× spread on the same value set and the same bel is the evidence for
under-fuzzing rather than a hardware limit.

**Caveat that must travel with this**, or the fix will be aimed wrongly:
`PICL1` — the well-resolved reference — has **no bonded pad on any ECP5 device or
package**. Whatever produced its 28 encodings was not a bonded-pin build, so it may
be the *less* trustworthy entry rather than the model answer. See the follow-up on
#85 and `scripts/ecp5_pad_targets.py`.

**MachXO2 is different and the distinction is easy to lose:** every MachXO2 PIC
tile resolves 87–90 values into 36–38 encodings — a best/worst spread of **1.00×**.
The aliases are real, but there is no internal evidence they are *wrongly* aliased,
and no reference tile to read correct encodings from. Claims that MachXO2 input
standards are "decoded on a coin flip" overstate the data.

### DEFECT candidates — database self-consistency
`scripts/trellis_db_check.py` counts, per family:

| detector | ECP5 | MachXO2 |
|---|---:|---:|
| D1 overlap-across-fields | 554 | 342 |
| D2 enum round-trip aliases | 3,116 | 3,434 |
| D3 duplicate encodings | 827 | 1,408 |
| D4 mux-bit collision | 1,459 | 18 |
| D4 mux round-trip | 0 | 243 |
| D5 ragged enum | 1,539 | 101 |

Credibility rests on the detectors mechanically reproducing two bugs previously
found by hand: the `PULLMODE`/`BASE_TYPE` bit overlap, and `EBR.MODE` making
`DP8KC` indistinguishable from `PDPW8KC`.

These are **candidates**, not confirmed defects — the counts include cases that may
be genuine hardware indistinguishability.

### GAP — strict subset of the vendor's tile database
The vendor BFD (dumped with `bstool`) has 198 ECP5 tile types; trellis `tiledata/`
has 185. All 185 are in the vendor database and **none is wrong** (#93).

That is an endorsement of trellis's accuracy as much as a gap, and it turns "what
else is missing?" into a finite list: `PLC`, `PVT_COUNT`, `DUMMY_TILE_3`, `BMID_0`,
`BMID_1`, and eight `BANKREF*` variants.

### GAP — timing data
1,051 timing entries against Diamond's ~10,300 conditioned arcs per speed grade,
and 10 I/O standards against 34 (#93). Whether the *numbers* agree where both exist
is unestablished, and the arc-name mapping needed to check is explicitly not worked
out. Timing errors are invisible until a design mysteriously fails.

### CORRECT — and better than the vendor
Worth recording, because the reflex is to trust the vendor: prjtrellis's
`SED_CLK_FREQ` list tops out at 62.0 and **matches Diamond's mapper**, while
Lattice's own simulation model documents values the mapper rejects (see DOC-WRONG
below). The open database is the more accurate source here.

### OPEN — MachXO family parses to nothing
All 71 `MachXO` tiles yield zero enums, zero muxes and zero words. Structurally
empty rather than sparse, which suggests a parse failure rather than an
undocumented family — possibly ours (#96).

### OPEN — detector asymmetry
ECP5 shows 1,459 mux/config collisions against MachXO2's 18, but **zero** mux
round-trip failures against MachXO2's 243 — opposite directions from one
family-agnostic detector. More likely a detector bug than a real asymmetry (#96).

---

## yosys

### GAP — no `SEDGA` in `cells_bb.v`
Synthesis fails outright with `ERROR: Module '\SEDGA' is not part of the design`.
A **9-line blackbox** declaration fixes it; verified to synthesise cleanly and emit
`1 SEDGA` cell. Needs `(* keep *)` or the optimiser sweeps the primitive away.
Written out in `docs/ecp5-sedga.md` (#88, #96).

---

## nextpnr-ecp5

### GAP — no `id_SEDGA` branch in the bitstream writer
Placement and routing already work — nextpnr knows SEDGA as a real bel with the
full port list and reports `SEDGA: 1/1 100%`. It then aborts in the bitstream
writer: `Assertion failure: unsupported cell type (ecp5/bitstream.cc:1559)`. Only
final config-word emission is missing (#88, #96).

**Now bypassable.** SEDGA is pure tile configuration, so with the byte-exact ECP5
encoder (#97) the route is decode → set `SED.*` in `EFB2_PICB0` → re-encode. The
upstream patch is no longer on the critical path for the use case.

### NOT A BUG — one chipdb per die, and the silicon agrees
`--12k` and `--25k` both report 24,288 LUT4s, because the chipdb is per-die and
LFE5U-12F and -25F are the same die (#98). This looks like a bug and is not; do not
file it. It is why a 12F can use the whole die with no IDCODE patching.

**Confirmed on hardware, 2026-07-30** (#98): a design occupying **20,143 / 24,288
LUT4s — 7,855 past the 12,288 the part advertises** — ran on a Cynthion r1.4 marked
`LFE5U-12F`, at 86.43 MHz against a 60 MHz constraint, for 22,026 self-checked
rounds across two runs with **zero** mismatches. `ecpunpack` reads the genuine 12F
IDCODE `0x21111043`; nothing was patched. The extra logic was placed across 44 of
47 tile rows, so the utilisation figure is not one dense corner.

The result is credible mainly because of its **negative control**: the same design
rebuilt with a deliberately wrong golden constant reported 1,575/1,575 rounds
mismatched on the same silicon, so the clean run measures something rather than
merely failing to fail.

What it does **not** establish: an intermittent per-part defect rate. Treating
rounds as independent trials, 0 failures in 22,026 bounds the per-round rate at
about **1.4e-4** (95%, rule of three) at one temperature and supply — which
constrains binning/salvage without excluding it, and says nothing about other
parts. The honest scope is "this part, these conditions".

---

## Lattice Diamond / vendor documentation

Not fixable upstream. Recorded so it is not re-trusted.

### DOC-WRONG — `SEDGA.v` documents frequencies the mapper rejects
`cae_library/simulation/verilog/ecp5u/SEDGA.v` lists
`2.4, 4.8, 9.7, 19.4, 38.8, 77.5, 155.0`. Diamond's `map` **rejects 77.5 and 155.0
on every device** — accounting for all 80 failures in a full sweep exactly
(2 × 2 × 5 × 4). Explanation found later: those are **OSCG** frequencies (base
310 MHz ÷ 2 and ÷ 4), and SED is clocked from OSCG, so the comment was copied from
the oscillator's range rather than SED's legal set. Note `62.0` is accepted and
appears in no Lattice comment (#89, #96).

### DOC-WRONG — `SEDGA.v`'s own default `DEV_DENSITY` does not work
Every `…KUM` spelling is rejected by `map` on every device, **including `85KUM`,
which is the file's own default**. Exactly one value works per device:
`12KU`/`25KU`/`45KU`/`85KU`. A design instantiating SEDGA without overriding
`DEV_DENSITY` will not map on any part (#89).

### DOC-WRONG — webhelp claims ReadCapture applies to ECP5
`bitgen -h ECP5U` lists exactly seven `-g` options and neither ReadBack nor
ReadCapture is among them (#92).

### DOC-WRONG — `GWEPHASE`, not `GWDPHASE`
ECP3 genuinely uses `GWDPHASE`, so this is a real ECP5 rename. The ECP5 `.usg`, the
binary help, and prjtrellis (reverse-engineered from silicon) agree against the
webhelp — three independent sources (#92).

### UNDOCUMENTED — `-g DisableUES:FALSE`
Appears on the real bitgen command line in a shipped ECP5 example build, and in no
usage text for any architecture (#92).

### TRAP — the device-tree names
`ep5c00` reads like "ECP5" and is **LatticeECP3**. ECP5 is `sa5p00`. This error was
in the brief that commissioned a sweep and propagated before being caught,
invalidating one reported finding (#92). Any conclusion citing `ep5c00` needs
re-auditing.

### The source hierarchy this establishes
Diamond's prose disagrees with Diamond's binaries, and **the binaries win**:

```
bitgen -h <arch> / binary strings  ≈  correct-tree .usg
   >  prjtrellis bits
      >  webhelp prose
         >  cae_library simulation models
```

Simulation models rank last because they are demonstrably wrong **in both
directions** — they overstate and understate. They are not documentation (#92, #96).

---

## apicula

### GAP — no correct pinout table for GW1N-2 / QN48
Package confirmed QN48 from the chip marking, but apicula ships no correct table
for this part, so pin mapping cannot be trusted from it (#73, #74).

---

## Adding to this file

Record: what, which project, the tag, the evidence (a command or a measured
number), the issue, and whether a patch exists. Prefer a measured count over an
adjective — "3,116 aliases" survives; "lots of problems" does not.

If a finding is later explained away, **leave it here and mark it explained**. The
`SED_CLK_FREQ`/OSCG entry is more useful as a solved puzzle than as a deleted one,
and the `ep5c00` trap is only valuable because the mistake is written down.
