# ECP5 toolchain gaps, found by automated detectors

Four detector scripts run over the whole surface — every primitive, every tile,
no sampling. Results below are independently re-verified here where stated.

## Confirmed: `BASE_TYPE` is degenerate in `PICL0`

`PIOA.BASE_TYPE` holds the same 84 I/O-standard values in both tiles. The
encodings do not match:

| tile | values | distinct encodings |
|---|---|---|
| `PICL0` | 84 | **3** |
| `PICL1` | 84 | **28** |
| `PICL0` `PIOB` | 40 | 2 |
| `PICL1` `PIOB` | 40 | 15 |

Re-verified directly against
`share/trellis/database/ECP5/tiledata/*/bits.db`.

In `PICL0` every `INPUT_*` standard — LVCMOS12 through LVDS — encodes to zero
bits, so they are mutually indistinguishable in any bitstream. `PICL1`
resolves the same value set into 28 encodings and does tell LVCMOS12 from
LVCMOS33 from SSTL15.

That asymmetry is what makes this under-fuzzing rather than a hardware
limitation: identical value sets on the same bel, and one tile shows what the
right answer looks like.

Scale: 1869 degenerate aliases on ECP5 and **3044 on MachXO2** — and
pluribus's MachXO2 support is production, so it is currently decoding input
standards by coin flip.

The detectors' credibility rests on mechanically reproducing both bugs that
were previously found by hand: the `PULLMODE`/`BASE_TYPE` overlap (D1,
`LLC3PIC_VREF3`, `F12B0`) and `EBR.MODE` (`DP8KC` indistinguishable from
`PDPW8KC`).

## Two premises that were wrong

**nextpnr-ecp5 already has full IOLOGIC support.** The MachXO2 gap does not
replicate. `pack.cc` (1717-2600) packs `IDDRX1F`, `ODDRX1F`, `ODDRX2F`,
`IDDRX2F`, `IDDR71B`, `ODDR71B`, `OSHX2A`, the DQS family, `DQSBUFM`,
`DELAYF/G`, `CLKDIVF`, `ECLKSYNCB` and `DDRDLLA`.

**`fuzzers/ECP5/105-sedga/` exists.** SEDGA's gap is one layer higher: yosys
never declares it in `cells_bb.v`. A much smaller fix than fuzzing it.

## The genuine IOLOGIC-shaped gap

`DLLDELD` is fuzzed (`132-dlldel`), declared by yosys, and present in
nextpnr's `constids.inc:1239` and `gfx.cc` — but `pack.cc`, `bitstream.cc`,
`cells.cc` and `arch.cc` do not mention it. Declared, drawable, unplaceable.

`PUR` is worse: yosys declares it and nextpnr has no constid at all.

## Correction to the readback lead

`ReadBack FLASH,SRAM` and `ReadCapture Disable,Enable` appear only under
`or5g00`/`mg5g00`, which are LatticeSC/ECP2-era trees. **No `ep5*`
`bitgen.usg` documents either.** So this does not overturn the earlier
conclusion that the ECP5 has no configuration readback — the earlier reading
conflated device trees.

`-m` is documented for ECP5 and unsupported by `ecppack`, but what it actually
emits is still unestablished.

Six `bitgen -g` settings are ECP5-documented and absent from every open tool:
`CfgMode`, `DONEPHASE`, `GOEPHASE`, `GSRPHASE`, `GWDPHASE`, `RamCfg`.

## Not done

The **fuzzer re-run differential** and the **Diamond round-trip differ** are
specified but were not executed. No Diamond was run and no bitstream generated,
so nothing in those sections is a result.

The round-trip differ is the obvious next step: two targets on a `PICL0` pad
would confirm the `BASE_TYPE` diagnosis and let the correct encodings be read
off directly, turning this from a report into a fix.

Two unexplained asymmetries also remain. ECP5 has 1459 mux/config collisions
against MachXO2's 18, but zero mux round-trip failures against MachXO2's 243 --
opposite directions from a family-agnostic detector. And `MachXO` parses to
zero enums, muxes and words across all 71 tiles, which is structurally empty
rather than merely sparse.
