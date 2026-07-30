# Testing the ECP5 lifter on bitstreams we did not build

The lifter passed 18/18 designs, but every one was built by our own toolchain
and checked against nextpnr's own placed netlist. A closed loop: it could not
catch anything about how a different toolchain lays out a bitstream.

**243 bitstreams later, the loop is open** — and the result is mostly
reassuring, with one real finding.

## The corpus

Two independent ways of breaking the loop:

- **228 third-party bitstreams** from 24 projects — ULX3S/ULX4M retro cores,
  SaxonSoc/LiteX/VexRiscv Linux SoCs, Colorlight, iCESugar-Pro, OrangeCrab,
  ECPIX-5, tinySDR, Machdyne. Build flow was read from each file's own ASCII
  header rather than assumed: **55 Diamond-built, 173 open-flow**.
- **15 Diamond 3.14 builds** of designs written for the purpose, across
  25F/45F/85F — a genuinely different synthesiser, packer, router and bitgen,
  with a known source design to check against.

Coverage reached **9 of the 10 ECP5 parts** in the database, including
LFE5UM/LFE5UM5G SERDES variants and all four die sizes. `geometry_for` held for
every one, despite only the 12F having been exercised before.

## The three claims, kept separate

| claim | result |
|---|---|
| decoded | **243/243**, every CRC verified, every frame consumed |
| identical to `ecpunpack` | **243/243, zero differences** |
| lifted and consistency-checked | 92+ (subset, pass still running) — zero fused nets, zero dropped LUTs, zero malformed INITs |

17.3M arcs across 586k tiles all matched the oracle.

## The main finding: real designs hit the clock-global gap far harder

| designs | flip-flop clocks lost |
|---|---|
| ours, including all 15 Diamond builds | **0%** |
| real-world | **median 43%** (range 9.9-68.6%) |

Root cause confirmed by inspecting decoded configs: the dropped globals are
`G_DCS*`, `G_HPFE*` and PLL outputs. **Our designs clock straight from a pad**,
so they only ever exercise the `G_HPBX`/`G_VPTX` class that prjtrellis does
position. Real designs use PLLs and clock dividers, which it does not.

That is precisely the blind spot a self-built corpus cannot reveal, and it is
upstream in prjtrellis rather than in the lifter.

Wide muxes are near-universal too — **204 of 211 decoded designs**, roughly
493k arcs — a gap the original 18-design suite barely touched.

**Every gap under-connects. The corpus-wide fused-net count is zero.** That
confirms the safe-direction claim on data that could have falsified it, which
is the strongest form the claim has had.

## Two harness bugs, both manufacturing false failures

Worth recording because both looked like decoder divergence:

1. Fetch keyed files on owner plus basename, so assets published under multiple
   release tags overwrote each other — 34 manifest entries described bytes not
   on disk.
2. Decode output paths keyed on label, so concurrent workers on same-basename
   files produced a spurious **12,641-line ORACLE-DIFF** that vanished on
   serial re-run.

Both were verified as harness bugs before being fixed, rather than assumed.

Two consistency checks were also corrected for firing on correct behaviour:
DPRAM's two-cells-per-output, and folded all-zero LUT INITs.

## Boundaries

No third-party binaries are committed. `corpus/` is gitignored; the manifest —
URL, licence, device, SHA-256, date — is committed, and `--verify` re-hashes it
(228/228 match). Verified here: the branch contains **zero `.bit` files**.

## Caveat

The lift pass covers a subset in roughly corpus order, not a random sample, so
those rates are indicative rather than complete. **The decode and oracle counts
are complete.**
