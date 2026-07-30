# SEDGA on ECP5: the encoding was never missing

Soft-error detection reads a CRC over the configuration memory and raises
`SEDERR` when a bit has flipped. It was the one ECP5 introspection primitive the
open flow could not instantiate, and the assumption here was that its bit
encoding needed reverse-engineering.

**That assumption was wrong.** prjtrellis already has the encoding, correctly,
and device-independently. The gap is two small omissions further up the stack.

## What already exists

    fuzzers/ECP5/105-sedga/                     the fuzzer
    ECP5/tiledata/EFB2_PICB0/bits.db            SED.CLK_FREQ, SED.CHECKALWAYS,
                                                SED.SEDEXCLK_USED
    libtrellis Bels.cpp:647, Chip.cpp:263       a SEDGA BEL
    ecpunpack / ecppack                         already round-trip it

Verified here directly against the installed database.

The encoding was checked against real silicon rather than trusted: **200 of 200
built targets round-tripped bit-exactly** (`.bit` → config → `.bit` → config),
and the SED tile contains only the expected `SED.*` enums with **zero `unknown:`
bits** — every bit Diamond sets there is accounted for.

Device-independence was tested rather than assumed: the same `EFB2_PICB0` tile
type appears on 12F, 25F, 45F and 85F, with only the row coordinate shifting
with die size. Seven `(param, value)` pairs are common to all four, and none is
device-specific. The primary sweep ran on `LFE5U-12F-8BG256C` — the exact
Cynthion r1.4 part — rather than a proxy.

## The actual gap

| tool | state |
|---|---|
| **yosys** | no `SEDGA` in `cells_bb.v`, so synthesis fails outright |
| **nextpnr** | places and routes SEDGA fine, then aborts at bitstream generation |

nextpnr's `ecp5/bitstream.cc` has no `id_SEDGA` branch and hits
`NPNR_ASSERT_FALSE("unsupported cell type")`. Only the final config-word
emission is missing.

The yosys blackbox needs `(* keep *)` or the optimiser sweeps the primitive away.
Both patches are written out in `pluribus/docs/ecp5-sedga.md`.

## Diamond contradicts its own documentation

The full cross-product was swept with no pruning, and the 80 build failures were
the informative part.

**`SED_CLK_FREQ` 77.5 and 155.0 do not exist.** Lattice's own `SEDGA.v` comment
lists them:

    parameter SED_CLK_FREQ = "2.4";   // 2.4, 4.8, 9.7, 19.4, 38.8, 77.5, 155.0

Diamond's `map` rejects both on every device, and that accounts for all 80
failures exactly (2 x 2 x 5 x 4). prjtrellis's list tops out at 62.0 and matches
the mapper. So **the open database is more accurate than the vendor's own
simulation model** — and note 62.0 is in the database and accepted by `map`
while appearing nowhere in Lattice's comment.

**`DEV_DENSITY` must match the device, and every `...KUM` spelling is
rejected** — including `85KUM`, which is `SEDGA.v`'s own default. A dedicated
32-build sweep found exactly one working value per device: 12F→`12KU`,
25F→`25KU`, 45F→`45KU`, 85F→`85KU`. **A design that does not override the
default will not map on any part.**

Input tie-offs were swept and do not affect the SED configuration bits.

`SED.SEDEXCLK_USED` stayed `NO` throughout, because that port is not on the
ECP5 primitive — reaching `YES` needs netlist-level fuzzing rather than Verilog
instantiation. Not covered.

## Infrastructure fixed

`run_all_fuzz.py` hardcoded `--device LCMXO2-1200` at line 240, which is why all
3178 pre-existing results are MachXO2. Device and package are now derived per
target from each project's `.ldf`, with overrides. MachXO2 targets still resolve
to exactly `LCMXO2-1200`/`TQFP100`, so the existing corpus is unaffected.

## Two things flagged

**pluribus bug**: `scripts/trellis_unpack.py`, the native pure-Python decoder,
**cannot decode ECP5 bitstreams at all** — `crc fail at offset 173` on every
`.bit`, including a trivial baseline. It was written for MachXO2. Reference
`ecpunpack` was used instead rather than working around it silently.

**Not filed upstream.** The yosys blackbox and nextpnr branch are documented but
not submitted; both are public repositories we do not own, so that needs
explicit approval first.
