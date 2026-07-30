# Commercial FPGA firmware hunt: state and handover

The corpus has 228 third-party ECP5 bitstreams, and **all of them are GitHub
open-hardware projects** — ULX3S, Colorlight, OrangeCrab, ECPIX-5. Roughly 180
are ULX3S-family. So it is third-party without being foreign: same open
toolchains, same hobby idioms, mostly one board.

Commercial firmware is a different population, and that is what this hunt is
for.

## Why it matters, in one number

| designs | flip-flop clocks lost by the lifter |
|---|---|
| ours, **including 15 Diamond builds** | **0%** |
| third-party hobby designs | **median 43%** (9.9-68.6%) |

Ours clock straight from a pad, so they only ever exercise the global class
prjtrellis positions. It was **design style, not toolchain**, that exposed the
gap — even Diamond-built versions of our own designs showed 0%. Commercial
designs, built by engineers who never touch the open flow, are the next step out.

## Scope: every FPGA bitstream is a candidate

pluribus has four working lifters, and the carver only recognises one preamble:

| family | lifter | maturity | part strings |
|---|---|---|---|
| **MachXO2** | 74K | **production** | `LCMXO2-*` |
| ECP5 | 28K | working | `LFE5U*` |
| Gowin | 19K | less exercised | `GW1N*`, `GW2A*` |
| Anlogic | 8K | less exercised | `EG4*`, `EF2*` |

`ecp5_carve.py` only looks for the ECP5 preamble `ff ff bd b3`, so Gowin and
Anlogic bitstreams inside firmware blobs are walked straight past.

**Priority order by what the harness most needs:** MachXO2 first — production
support, **3044 degenerate `BASE_TYPE` aliases** against ECP5's 1869, and *no
real-world corpus at all*. Then ECP5, then Gowin and Anlogic.

## The best lead: FNIRSI

Prior work in this repository already identified the silicon, which is normally
the expensive step:

    boards/fnirsi-eg4s20/   board.toml, pins.tsv             Anlogic EG4S20
    boards/fnirsi-gw1n2/    board.toml, open_questions.tsv   Gowin GW1N-2

plus `fnirsi_tb.vcd` (435 KB) at the repo root, so someone was simulating one.

FNIRSI is consumer test equipment — oscilloscopes, meters, component testers —
and publishes firmware updates, routinely mirrored on forums. Genuinely
commercial, closed-source, vendor-tool-built.

**Read `open_questions.tsv` first.** It likely records what the previous
investigator wanted and could not get, which is a better steer than starting
cold. Corpus currently has **zero** FNIRSI entries.

## Two obstacles to plan for

**The bitstream is usually embedded.** FPGA designs are often loaded from a host
rather than shipped as a standalone flash image, so a firmware package typically
contains the bitstream inside a larger file. Scan for the family preamble and
the ASCII part string. Extracting a bitstream from a firmware blob is itself a
capability worth having.

**Some will be encrypted or security-fused and will not decode.** That is a
legitimate finding. Establishing that commercial designs are commonly encrypted
would itself bound what this kind of testing can ever cover.

## Boundaries

- **No third-party binaries committed.** `corpus/` is gitignored; commit only
  the manifest — URL, product, vendor, licence status, device, family, SHA-256,
  date — following the existing schema so the sets merge.
- Downloading a publicly offered firmware file to test a decoder is ordinary
  interoperability work. **Do not redistribute it.**
- **Skip anything requiring authentication, payment, or accepting terms that
  forbid this use.** Record what was skipped and why; that list is informative.
- Do not attempt to defeat DRM or encryption.
- **Cynthion is ours — exclude it.** Great Scott Gadgets products are not
  commercial targets here, and our own bitstreams must not enter the corpus.
  Adding them would inflate the count while testing nothing.

## Testing

Keep three claims separate, as the ECP5 corpus work did:

1. **decoded** — CRC verified, all frames consumed
2. **matched the reference decoder** — the only oracle available without source
3. **lifted, consistency checks pass** — no unconnected nets, no impossible LUT
   INITs, counts agreeing with the tile census

Known lifter gaps, all of which **under-connect rather than mis-connect**: wide
muxes (F5MUX/PFUMX/L6MUX21), the CCU2 carry path, and clock globals. The
headline question is whether commercial designs hit these harder than hobby ones
did.

## Rebuild

`scripts/ecp5_corpus_rebuild.py` drives fetch, carve, test and report in one
command, each stage skippable. Verified at 228 of 228 present with all
checksums matching.

## State at handover

Nothing fetched yet. The scope above is the accumulated brief; no commercial
firmware has been located or tested.
