# ECP5 work in pluribus: what was done, where it lives

Record of the ECP5 toolchain work, kept here because it was driven from this
project even though the code belongs in `pluribus`.

The dividing line used throughout: **would this be useful to someone with a
different ECP5 board?** If yes, it goes in pluribus. Toolchain findings, bit
encodings and fuzzing pass that test; Moondancer and the Cynthion measurements
do not.

## Branches, all committed, none pushed

| branch | commits | what |
|---|---|---|
| `ecp5-lifter` | 1 | lifter stub to working; ECP5 bitstream decode fixed |
| `ecp5-sedga` | 2 | SEDGA fuzzed; gap traced to yosys/nextpnr |
| `ecp5-toolchain-gap-matrix` | 1 | automated detectors for gaps and wrong database entries |
| `ecp5-real-world-corpus` | 7 | 243-bitstream corpus and results |

## Issues filed

| # | subject |
|---|---|
| 85 | `BASE_TYPE` degenerate in `PICL0` — 84 I/O standards to 3 encodings |
| 86 | `trellis_unpack.py` cannot decode ECP5 bitstreams (**fixed** on `ecp5-lifter`) |
| 87 | `run_all_fuzz.py` hardcoded to MachXO2 |
| 88 | SEDGA gap is yosys blackbox plus nextpnr branch, not fuzzing |
| 89 | Lattice's `SEDGA.v` documents values Diamond rejects |
| 90 | tracking: four branches ready, blocked on hardcoded paths |

## Results worth carrying forward

**The lifter works.** Decode is byte-identical to `ecpunpack` on 243 bitstreams,
including a 105,603-line design. 18/18 self-built designs round-trip with
site-exact LUT and FF placement, zero split nets and zero fused nets. MachXO2 is
unaffected — 144/144 tests, CRAM bit-identical.

**trellis is more trustworthy than expected.** Diffing 198 vendor tiles from
Diamond's own BFD: **zero wrong, zero invented, 13 missing.** And where
Lattice's simulation model and prjtrellis disagreed on SEDGA clock frequencies,
prjtrellis was right and the vendor comment wrong.

**But `BASE_TYPE` is genuinely broken.** 84 I/O standards collapse to 3
encodings in `PICL0` where `PICL1` resolves them to 28. 1869 aliases on ECP5 and
**3044 on MachXO2**, whose support is production — so input standards are
currently decoded by coin flip.

**Real designs exercise gaps self-built ones cannot.** Median 43% of flip-flop
clocks lost on third-party designs against **0% on ours, including 15 Diamond
builds** — because our designs clock straight from a pad and only ever touch the
global class prjtrellis positions. Design style mattered more than toolchain.

Every gap **under-connects**; the corpus-wide fused-net count is zero. That is
the safe direction, now confirmed on data that could have falsified it.

## Blocked on

Roughly 28 added lines embed a specific machine's filesystem layout as defaults
— trellis database root, `ecpunpack` path, test-corpus location. Several already
have `os.environ.get()` fallbacks, so only the defaults are wrong. `pluribus` is
public, so this must be resolved before pushing. Commit `fc75e153a` solved the
same class of problem and is the pattern to follow.

## Not filed upstream

Two patches documented but unsubmitted, since yosys and nextpnr are
repositories we do not own: a `SEDGA` blackbox for `cells_bb.v`, and an
`id_SEDGA` branch in `ecp5/bitstream.cc`. nextpnr already places and routes
SEDGA — only bitstream emission is missing.

## Corpus

`pluribus/corpus/` — 130 MB, 220 bitstreams on disk, gitignored. Only
`manifest.json` is committed (URL, licence, device, SHA-256, date), and
`--verify` re-hashes it 228/228.

All 228 came from GitHub open-hardware projects; **none is commercial product
firmware**, and roughly 180 are ULX3S-family. So the corpus is third-party
without being foreign — same open toolchains, same idioms, mostly one board.
207 of 228 are unlicensed build artefacts, so it is not redistributable and
anyone reproducing it re-fetches from the manifest.

## Related findings that live elsewhere

Some ECP5 facts were established on Cynthion hardware and are documented in that
project, because they are entangled with board-specific detail. Summarised here
so they are discoverable:

**The configuration engine, probed on live silicon.** Lattice's own procedure
file defines **104 JTAG opcodes**. Testing them on hardware found that `JUMP`
(0x7E) is inert, that configuration writes while `DONE=1` are **silently
ignored** — no FAIL, no BUSY, `DONE` never drops — and that four opcodes return
real values, including a 64-bit unique die ID. Four others returned plausible
data that was **not stable across repeats**: shift-path residue, which a sweep
without repetition would have reported as working registers.

Two safety notes for anyone repeating it: `LSC_DEVICE_CTRL` (0x7D) **arms
`ISC_ERASE`**, and opcode **0xD1 is aliased** to both `LSC_READ_TRIM` and
`LSC_PROG_TRIM` — trusting the read-sounding name would permanently write analog
trim fuses.

The methodological finding generalises beyond ECP5: **an opcode issued without
walking the TAP through RUN-TEST/IDLE is indistinguishable from an opcode the
silicon does not implement.** Both read back inert. A first sweep reported every
configuration opcode as dead for exactly this reason, and it was caught only by a
positive control that asserted documented transitions actually occur.

**Bitstream options Diamond has and `ecppack` lacks**, confirmed in the real
ECP5 tree (`sa5p00`, not `ep5c00` — see `diamond-family-trap.md`): `-m` for mask
and readback files, `-sei` for soft-error injection with `-site`, plus `CfgMode`,
`RamCfg`, `DONEPHASE`, `GOEPHASE`, `GSRPHASE`, `GWEPHASE` and `ES`.

`-sei` pairs directly with SEDGA: inject a soft error, then let the device's own
CRC detect it.
