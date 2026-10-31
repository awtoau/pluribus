# ECP5 SEDGA — status, encoding, and what is actually missing

`SEDGA` is the ECP5 soft-error-detection block.  It runs a CRC over the
*configuration memory* and asserts `SEDERR` when a configuration bit has
flipped; with `CHECKALWAYS=ENABLED` it re-runs continuously in the
background.  For long-run hardware soak testing that distinguishes "the run
failed" from "the run failed *and the loaded bitstream was corrupt at the
time*", which no external instrument can tell you.

## Headline finding

**The SEDGA bit encoding did not need to be reverse-engineered — prjtrellis
already has it, correctly, and it is device-independent across the ECP5
family.  The gap is one missing `else if` in nextpnr and one missing
blackbox in yosys.**

This inverts the premise the work started from.  What follows is the
evidence.

## What already exists (verified, not assumed)

| Layer | SEDGA support | Evidence |
|---|---|---|
| prjtrellis fuzzer | **present** | `fuzzers/ECP5/105-sedga/` (fuzzer.py, sed.ncl, sed_routing.ncl) |
| prjtrellis tile DB | **present** | `ECP5/tiledata/EFB2_PICB0/bits.db` — `SED.CLK_FREQ`, `SED.CHECKALWAYS`, `SED.SEDEXCLK_USED` |
| prjtrellis BEL | **present** | `libtrellis/src/Bels.cpp:647`, `Chip.cpp:263` (`add_misc(..., "SEDGA", ...)`) |
| `ecpunpack` | **present** | decodes SED enums from Diamond bitstreams |
| `ecppack` | **present** | re-encodes SED enums bit-exactly |
| nextpnr BEL/placement | **present** | `ecp5/constids.inc`, `arch.cc:1035`, `gfx.cc:160` |
| **nextpnr bitstream gen** | **MISSING** | `ecp5/bitstream.cc` has no `id_SEDGA` branch → `NPNR_ASSERT_FALSE("unsupported cell type")` |
| **yosys `cells_bb.v`** | **MISSING** | no `SEDGA` module → `ERROR: Module \SEDGA ... is not part of the design` |

The two missing pieces are the *only* things standing between the open flow
and a working SEDGA instantiation.

## The encoding (as shipped by prjtrellis, confirmed against Diamond)

Tile type `EFB2_PICB0`, one instance per device:

```
.config_enum SED.CHECKALWAYS DISABLED
DISABLED -
ENABLED  F68B1

.config_enum SED.CLK_FREQ NONE
NONE  -
2.4   F84B1 F86B1
4.8   F70B1 F84B1 F86B1
9.7   F80B1 F84B1 F86B1
19.4  F78B1 F80B1 F84B1 F86B1
38.8  F76B1 F78B1 F80B1 F84B1 F86B1
62.0  F70B1 F72B1 F76B1 F78B1 F80B1 F84B1 F86B1

.config_enum SED.SEDEXCLK_USED YES
YES -
NO  F82B1
```

### Device-independence — tested, not assumed

The tile *type* is `EFB2_PICB0` on all four densities swept; only its row
coordinate moves with die size:

| Device | SED tile |
|---|---|
| LFE5U-12F (Cynthion r1.4) | `MIB_R50C6:EFB2_PICB0` |
| LFE5U-25F | `MIB_R50C6:EFB2_PICB0` |
| LFE5U-45F | `MIB_R71C6:EFB2_PICB0` |
| LFE5U-85F | `MIB_R95C6:EFB2_PICB0` |

The frame/bit offsets *within* the tile are shared (they live in the tile
type, not the device), so the encoding is family-wide.  Device-independence
check over 200 targets: 7 `(param,value)` pairs common to all four devices,
**0** pairs seen on some devices but not others.

## Verification method and result

Bit positions were not eyeballed.  For all 200 successfully-built targets:

1. Diamond `.bit` → `ecpunpack` → `.config`
2. `.config` → `ecppack` → `.bit`
3. `.bit` → `ecpunpack` → `.config`
4. compare SED enums between (1) and (3)

**Result: 200/200 exact.  Zero mismatches.**  A wrong-but-self-consistent
database could survive a name-level round-trip, so this is backed by the
diff-against-baseline analysis too: for every target, the SED tile contains
*only* the expected `SED.*` enums and **no `unknown:` bits**, i.e. every bit
Diamond sets in that tile is accounted for by the existing database.

`analyse_sedga_bits.py` additionally attributes bits by exact partition —
a bit is credited to a parameter only if it is present in every target with
that value and absent from every target with any other value.  Both
`SED_CLK_FREQ` and `CHECKALWAYS` partition cleanly and land solely in
`EFB2_PICB0`.

## Sweep findings (Diamond disagrees with its own documentation)

The sweep was the full cross-product (no pruning), 284 targets across 4
devices: 7 `SED_CLK_FREQ` × 2 `CHECKALWAYS` × 5 input tie-off variants, plus
a SEDGA-free baseline per device.  204 built, 80 failed — and the failures
are results:

1. **`SED_CLK_FREQ` 77.5 and 155.0 are rejected by Diamond's mapper**, on
   every device, despite both being listed in Lattice's own
   `cae_library/simulation/verilog/ecp5u/SEDGA.v` comment
   (`// 2.4, 4.8, 9.7, 19.4, 38.8, 77.5, 155.0`).

       ERROR - map: Value 155.0 for property SED_CLK_FREQ on block u_sedga is invalid.

   That accounts for all 80 failures (2 freqs × 2 checkalways × 5 tie-offs ×
   4 devices).  prjtrellis' fuzzer list — which tops out at `62.0` — matches
   the mapper, not the simulation model.  **The simulation model's comment is
   wrong.**

2. **`DEV_DENSITY` is not a free parameter — it must match the device**, and
   the accepted spellings are *not* the ones in `SEDGA.v`.  A dedicated
   32-build sweep (4 devices × 8 spellings, `probe_sedga_density.py`) found
   exactly one accepted value per device:

   | Device | Accepted | Rejected |
   |---|---|---|
   | LFE5U-12F | `12KU` | `12KUM`, `25KU`, `25KUM`, `45KU`, `45KUM`, `85KU`, `85KUM` |
   | LFE5U-25F | `25KU` | all others |
   | LFE5U-45F | `45KU` | all others |
   | LFE5U-85F | `85KU` | all others |

   Every `...KUM` spelling is rejected by `map` on every device — including
   `85KUM`, which is `SEDGA.v`'s own *default value*.  A design that
   instantiates SEDGA without overriding `DEV_DENSITY` will not map on any
   part.  Note `12KU` is accepted for the 12F even though `SEDGA.v` only
   mentions 12KUM/12KU in a comment branch and lists `25KUM, 45KU, 45KUM,
   85KUM` in the parameter comment.

3. **Input tie-offs do not change the SED configuration bits.**  All five
   tie-off variants produce identical `SED.*` enums; they differ only in
   IO/routing tiles.  Expected, but it was swept rather than assumed.

4. **`SED.SEDEXCLK_USED` is always `NO` in this sweep.**  None of these
   designs route an external clock to `SEDEXCLK`; the port is not on the
   ECP5 `SEDGA` primitive at all (it exists on MachXO2's `SEDFA`).  The
   enum is in the ECP5 database because the tile supports it, but reaching
   `YES` needs `sed_routing.ncl`-style netlist-level fuzzing, not a Verilog
   instantiation.  Not covered here.

## A pluribus bug found along the way

`scripts/trellis_unpack.py` (the native pure-Python decoder) **cannot decode
ECP5 bitstreams**.  Every ECP5 `.bit` tried — including the trivial
SEDGA-free baseline — aborts with:

    native_bitstream.ParseError: crc fail at offset 173:
        calculated 0x0cf3 but expecting 0x0000

The native decoder was written for MachXO2 and its CRC/frame handling does
not carry over.  Worth its own issue.  The scripts here use prjtrellis'
reference `ecpunpack` instead.

## What a fix looks like

### yosys — `share/yosys/ecp5/cells_bb.v`

```verilog
(* blackbox *) (* keep *)
module SEDGA(SEDENABLE, SEDSTART, SEDFRCERR, SEDCLKOUT, SEDDONE, SEDINPROG, SEDERR);
    parameter SED_CLK_FREQ = "2.4";
    parameter CHECKALWAYS = "DISABLED";
    parameter DEV_DENSITY = "25KUM";
    input SEDENABLE;
    input SEDSTART;
    input SEDFRCERR;
    output SEDCLKOUT;
    output SEDDONE;
    output SEDINPROG;
    output SEDERR;
endmodule
```

`(* keep *)` matters: SEDGA has no user-visible function the optimiser can
see, so without it a design that only watches `SEDERR` can be swept away.
This was tested — with the blackbox added, `synth_ecp5` completes and emits
`1 SEDGA` cell.

### nextpnr — `ecp5/bitstream.cc`

Add a branch alongside the existing `id_OSCG` / `id_USRMCLK` / `id_GSR`
cases, writing to the `EFB2_PICB0` tile:

```cpp
} else if (ci->type == id_SEDGA) {
    std::string tile = ctx->get_tile_by_type("EFB2_PICB0");
    cc.tiles[tile].add_enum("SED.CLK_FREQ",
                            str_or_default(ci->params, id_SED_CLK_FREQ, "2.4"));
    cc.tiles[tile].add_enum("SED.CHECKALWAYS",
                            str_or_default(ci->params, id_CHECKALWAYS, "DISABLED"));
```

`SED_CLK_FREQ` and `CHECKALWAYS` need `constids.inc` entries.  Legal
`SED.CLK_FREQ` values are `NONE, 2.4, 4.8, 9.7, 19.4, 38.8, 62.0` — note
**62.0, not 77.5/155.0**, per finding 1 above.  `DEV_DENSITY` is a
Diamond-side mapping constraint with no bitstream representation, so
nextpnr should ignore it rather than encode it.

## Current open-flow status (measured)

With only the yosys blackbox added and nextpnr unpatched:

- `yosys synth_ecp5` — **passes**, emits 1 SEDGA cell
- `nextpnr-ecp5 --12k --package CABGA256` — **places and routes SEDGA
  successfully** (`Source u_sed.SEDINPROG` appears in the timing report,
  routing completes), then dies at bitstream generation:

      terminate called after throwing an instance of 'nextpnr_ecp5::assertion_failure'
        what():  Assertion failure: unsupported cell type (ecp5/bitstream.cc:1559)

So placement and routing already work end to end.  Only the final
config-word emission is missing.

## Reproducing

```bash
# 1. generate the full cross-product (284 targets, 4 devices)
python3.15t diamond-fuzz/scripts/gen_sedga_targets.py --clean

# 2. build with Diamond (~10 min at -j6)
DIAMONDDIR=~/lscc/diamond/3.14 \
  python3.15t diamond-fuzz/scripts/run_all_fuzz.py \
    --targets 'sedga_*' --jobs 6 --no-pluribus

# 3. recover the encoding by diffing against the per-device baseline
python3.15t diamond-fuzz/scripts/analyse_sedga_bits.py

# 4. prove the encoding is right via bitstream round-trip
python3.15t diamond-fuzz/scripts/verify_sedga_encoding.py

# 5. (side sweep) which DEV_DENSITY does each device accept?
python3.15t diamond-fuzz/scripts/probe_sedga_density.py
```

Logs land in `tmp/logs/`; machine-readable results in
`tmp/sedga_encoding.json`, `tmp/sedga_verify.json`,
`tmp/sedga_density_matrix.json`.
