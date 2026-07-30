# ECP5 open-toolchain gap hunt — findings

Companion to [upstream-contributions.md](upstream-contributions.md) (the MachXO2
IOLOGIC precedent) and [fuzzing-coverage.md](fuzzing-coverage.md) (the
never-prune rule this work follows).

Everything here is produced by **detector scripts**, not by reading. Re-run them
as the databases change:

| script | what it detects |
|---|---|
| `scripts/trellis_db.py` | library: parser for prjtrellis `bits.db` (all 4 directives) |
| `scripts/trellis_db_check.py` | D1–D7 — prjtrellis data that is *wrong*, no oracle needed |
| `scripts/ecp5_gap_matrix.py` | the four-layer presence matrix over all 171 Diamond primitives |
| `scripts/diamond_harvest.py` | Diamond's own `.usg`/binaries vs what the open flow exposes |

Logs land in `tmp/logs/<name>.log`; machine-readable output in `tmp/*.json`.

---

## Reading guide: what is verified vs inferred

Stated precisely, because the distinction is the point of the exercise.

- **Verified by reading source** — every claim about prjtrellis decode
  semantics (`libtrellis/src/BitDatabase.cpp`), every bit encoding quoted from
  `bits.db`, every nextpnr-ecp5 claim (`pack.cc`, `bitstream.cc`, `constids.inc`),
  and every Diamond option quoted from a named `.usg` file.
- **Inferred** — anything labelled as such inline. There is little of it.
- **Not done** — no Diamond run, no bitstream generated, no hardware. The
  round-trip differ and the fuzzer re-run are specified below but **not
  executed**; treat their sections as a work plan, not as results.

---

## Correction to two premises I was given

Both were stated as starting points; both are wrong, and the scripts show it.

**1. "nextpnr-ecp5 has the same IOLOGIC gap as nextpnr-machxo2."** It does not.
The MachXO2 finding does not replicate. `nextpnr-ecp5/pack.cc` contains a full
IOLOGIC packer — `IDDRX1F`, `ODDRX1F`, `ODDRX2F`, `IDDRX2F`, `IDDR71B`,
`ODDR71B`, `OSHX2A`, `ODDRX2DQA`, `ODDRX2DQSB`, `IDDRX2DQA`, `TSHX2DQA`,
`TSHX2DQSA`, plus `DQSBUFM`, `DELAYF`/`DELAYG`, `CLKDIVF`, `ECLKSYNCB`,
`ECLKBRIDGECS`, `DDRDLLA`. ECP5 IOLOGIC is **covered**, not gapped. Verified by
reading `pack.cc` lines 1717–2600.

**2. "`SEDGA` is absent from prjtrellis — no ECP5 SED fuzzer exists."** A
fuzzer does exist: `fuzzers/ECP5/105-sedga/` (`fuzzer.py`, `sed.ncl`,
`sed_routing.ncl`). The real ECP5 SEDGA gap is one layer up — **yosys does not
declare `SEDGA` in `cells_bb.v`**, so the primitive cannot reach nextpnr at all.
That is a much smaller fix than fuzzing. Flagged for the agent working on SEDGA;
not touched here.

---

## Finding 1 — `BASE_TYPE` is degenerate, and unevenly so (the big one)

**Category: prjtrellis has the data and it is wrong.** This is the
`PULLMODE`/`BASE_TYPE` bug class, found mechanically rather than by hand, and it
is far larger than the known instance.

`D2-enum-roundtrip` writes each enum value into a blank tile and decodes it
back, reproducing `EnumSettingBits::get_value` exactly (longest-match wins,
`BitDatabase.cpp:242-267`). A value that does not round-trip to itself is a
defect: every open tool reading that bitstream reports the wrong I/O standard.

`PIOA.BASE_TYPE` in tile `PICL0`:

```
84 declared values  ->  3 distinct encodings
  30 values <- (no bits)              INPUT_LVCMOS12, INPUT_LVCMOS33, INPUT_LVDS, ...
  28 values <- F1B1 F1B4 F2B4 F3B6 F3B9 F4B9   BIDIR_LVDS, BIDIR_SSTL15D_I, ...
  26 values <- F1B4 F2B4              BIDIR_LVCMOS12, BIDIR_LVCMOS33, BIDIR_SSTL15_I, ...
```

Every `INPUT_*` standard — LVCMOS12 through LVDS — encodes to **zero bits** and
is therefore indistinguishable from every other input standard in any bitstream.

### Why this is under-characterisation, not hardware

The decisive evidence is that **the same field is characterised to different
resolution in different tiles of the same device**:

| tiles | values | distinct encodings |
|---|---|---|
| `PICL1`, `PICL1_DQS0`, `PICL1_DQS3`, `PICR1`, `PICR1_DQS0`, `PICR1_DQS3` | 84 | **28** |
| `PICL0`, `PICL0_DQS2`, `PICR0`, `PICR0_DQS2` | 84 | **3** |

Identical value sets (verified: `set(a.values) == set(b.values)` is `True`),
same `PIOA` bel, same left/right edges. Direct comparison:

| value | `PICL0` encoding | `PICL1` encoding |
|---|---|---|
| `BIDIR_LVCMOS12` | `F1B4 F2B4` | `F2B0 F4B0 F9B0` |
| `BIDIR_LVCMOS33` | `F1B4 F2B4` | `F2B0 F3B0 F3B1 F4B0 F4B1 F5B1 F6B1 F9B0` |
| `BIDIR_SSTL15_I` | `F1B4 F2B4` | `F2B0 F5B0 F5B1 F6B0 F7B0 F9B0` |
| `INPUT_LVCMOS12` | *(none)* | `F2B0 F4B0 F9B0` |
| `INPUT_LVCMOS33` | *(none)* | `F2B0 F3B0 F3B1 F4B0 F9B0` |

`PICL1` distinguishes LVCMOS12 from LVCMOS33 from SSTL15; `PICL0` cannot tell
any of them apart. The hardware is the same PIO. **`PICL0`/`PICR0` are
under-fuzzed**, and `PICL1` shows what the correct answer looks like.

### Scale, and it is not ECP5-specific

`D2` substantive aliases (encodings with bits, excluding all-default):

| family | total | `BASE_TYPE` share |
|---|---|---|
| ECP5 | 2398 | 1869 |
| MachXO2 | 3335 | 3044 |
| MachXO3 | 2649 | 2392 |
| MachXO3D | 1556 | 1352 |

**pluribus's MachXO2 support is production and is affected**: 3044 MachXO2
`BASE_TYPE` aliases means any `.config` naming an input standard is being
decoded on a coin-flip between ~30 candidates.

### Detector validation against ground truth

Both previously hand-found MachXO2 bugs are reproduced mechanically, which is
what makes the other 7495 findings credible:

- `PULLMODE`/`BASE_TYPE` overlap → `D1`, tile `LLC3PIC_VREF3`, bit `F12B0`,
  reported as `PIOA.BASE_TYPE & PIOA.OPENDRAIN & PIOA.PULLMODE`, severity
  `error` (same bel).
- `EBR.MODE` → `D2`, tile `EBR0`: `DP8KC` encodes identically to `PDPW8KC`.

---

## Finding 2 — detector totals across every family

Run: `scripts/trellis_db_check.py ECP5 MachXO2 MachXO3 MachXO3D MachXO`

| detector | ECP5 | MachXO2 | MachXO3 | MachXO3D |
|---|---|---|---|---|
| D1 overlap across fields | 554 | 342 | 403 | 246 |
| D2 enum round-trip fails | 3116 | 3434 | 2768 | 1635 |
| D3 duplicate encoding | 827 | 1408 | 1171 | 734 |
| D4 mux bit collision | 1459 | 18 | 18 | 20 |
| D4 mux round-trip fails | 0 | 243 | 262 | 151 |
| D5 ragged enum | 1539 | 101 | 114 | 74 |

Two asymmetries worth chasing, both currently **unexplained**:

- **ECP5 has 1459 mux/config bit collisions to MachXO2's 18** — an 80×
  difference in a detector that is family-agnostic.
- **ECP5 has zero mux round-trip failures where MachXO2 has 243.** Opposite
  direction. One of these families is characterised very differently from the
  other and it is not obvious which is right.

**`MachXO` (original) parses to 0 enums, 0 muxes, 0 words across all 71 tiles** —
the tile databases are structurally empty. Not a subtle finding, but worth
recording: nothing downstream can be reading meaningful MachXO tile data.

---

## Finding 3 — the four-layer presence matrix

Run: `scripts/ecp5_gap_matrix.py` → `docs/ecp5-gap-matrix.md`, `tmp/ecp5_gap_matrix.json`.
All 171 Diamond `ecp5u` primitives, no sampling. Soft primitives (AND/OR/LUT/
FD1*/ROM*, techmapped to LUTs) and IO buffers (modelled as `TRELLIS_IO`) are
classified out as non-gaps, leaving the hard blocks.

**Implementable gaps — lower layers have data, nextpnr does not use it:**

| primitive | prjtrellis | yosys `cells_bb.v` | nextpnr-ecp5 | note |
|---|---|---|---|---|
| `DLLDELD` | fuzzer `132-dlldel` | declared (line 1159) | constid + gfx only | **the IOLOGIC-shaped gap** |
| `PUR` | no fuzzer | declared (line 9) | **absent entirely** | no constid at all |

Both verified by reading source, not by the count heuristic:

- **`DLLDELD`** — `constids.inc:1239` defines `X(DLLDELD)` and `gfx.cc:172`
  draws it, but `grep DLLDELD pack.cc bitstream.cc cells.cc arch.cc` returns
  **nothing**. Declared to the architecture, drawable in the GUI, and there is
  no packer to map it and no bitstream writer to emit it. This is precisely the
  MachXO2 IOLOGIC shape: prjtrellis fuzzed it (`fuzzers/ECP5/132-dlldel/`),
  yosys passes it through as a black box, nextpnr cannot place or emit it.
- **`PUR`** — yosys declares `module PUR(PUR)` but there is no `X(PUR)` in
  `constids.inc` and no reference anywhere in nextpnr-ecp5. A design
  instantiating `PUR` cannot survive the flow.

**Data gap, and the narrowest fix on this page:**

| `SEDGA` | fuzzer `105-sedga` **exists** | **not declared** | absent | one `cells_bb.v` stanza away from reaching nextpnr |

**Never fuzzed, never declared** (research, not engineering): `ALU24A`,
`ALU24B`, `ALU54A`, `MULT18X18C`, `MULT9X9C`, `MULT9X9D`, `PRADD18A`,
`PRADD9A`, `PLLREFCS`, `BUFBA`, `START`, and the `IFS1P3*`/`OFS1P3*`/`IFS1S1*`
input/output register families (these last are likely absorbed into IOLOGIC
packing rather than genuinely missing — **inferred, not verified**).

---

## Finding 4 — Diamond documents bitgen options the open flow lacks

Run: `scripts/diamond_harvest.py`. Parses all 77 `.usg` files, then cross-refs
every option against `strings` of `ecppack`, `ecpunpack`, `ecpbram`, `ecpmulti`,
`nextpnr-ecp5`, `nextpnr-machxo2`, `yosys`.

**Zero of the 27 documented `bitgen -g` settings appear in any open tool.**

Documented for ECP5 (`ep5*`) trees specifically, and absent from the open flow:

| setting | values |
|---|---|
| `CfgMode` | Disable, Flowthrough, Bypass |
| `DONEPHASE` | T3, T2, T1, T0 |
| `GOEPHASE` | T1, T3, T2 |
| `GSRPHASE` | T2, T3, T1 |
| `GWDPHASE` | T2, T3, T1 |
| `RamCfg` | Reset, NoReset |

These are startup-sequencing and configuration-mode controls. `ecppack` cannot
express any of them, so any design needing non-default DONE/GOE/GSR phasing is
unreachable through the open flow.

### Correcting the readback claim

I was asked to establish whether `bitgen -m` implies ECP5 configuration
readback, on the basis that `ReadBack` and `ReadCapture` appear in `bitgen.usg`.
**They do not appear in any ECP5 tree.** Attribution:

```
ReadBack     FLASH,SRAM      trees = mg5g00, or5g00
ReadCapture  Disable,Enable  trees = mg5g00, or5g00
```

`or5g00`/`mg5g00` are LatticeSC/ECP2-era families, not ECP5. Every `ep5*`
`bitgen.usg` documents `-m` (mask/readback file formats) but **none** documents
`ReadBack` or `ReadCapture`. So this evidence does **not** overturn the earlier
conclusion that the ECP5 lacks configuration readback — the options belong to
different silicon. The harvester now tracks per-tree attribution precisely
because conflating trees produces exactly this kind of false positive.

`-m` itself is documented for ECP5 and unsupported by `ecppack`; what it
actually emits is **not established** (would need a Diamond run).

### Vendor data is newer than the fuzzing — with dates

| file | size | mtime |
|---|---|---|
| `ep5c00a/data/ep5c00a.bfd` | 90.6 MB | 2024-09-27 |
| `ep5c00/data/ep5c00.bfd` | 83.4 MB | 2024-09-27 |
| `ep5m00/data/ep5m112x128.hrg` | 77.6 MB | 2024-09-27 |
| `ep5m00/data/ep5m112x128.spd` | 25.1 MB | 2024-09-27 |

475 device data files across the six ECP5 trees, **all dated 2024-09-27**.
`prjtrellis/fuzzers/ECP5/` was last touched **2022-04-29**. The ECP5 bit
database was therefore characterised against an older Diamond than the one
installed here, and nobody appears to have re-run the fuzzers since.

---

## Not executed — specified for whoever picks this up

Two detectors are designed but **not run**, and nothing above depends on them.

**Fuzzer re-run differential.** Re-run all 73 ECP5 fuzzers against Diamond 3.14
and diff against the committed database. Control for placer noise first: run one
target twice and diff those, to establish the run-to-run variation band; only
systematic same-tile same-setting differences are findings. A clean diff is a
genuinely useful negative result — it would establish that the 2022
characterisation still holds against a 2024 oracle, which nobody currently knows.
The same argument applies to MachXO2, whose fuzzers also predate this Diamond and
whose data pluribus depends on in production.

**Round-trip differ.** Build a design in Diamond, build the equivalent through
yosys/nextpnr, decode both, diff the config bits. This is the generalisation of
how `EBR.MODE` was found. `BASE_TYPE` is the obvious first target: instantiate a
`PICL0` pad as `INPUT_LVCMOS33`, then as `INPUT_LVCMOS12`, and check whether
Diamond's bitstreams differ. If they do, `PICL0` is confirmed under-fuzzed and
the correct encodings can be read straight off — Finding 1 becomes a fix rather
than a report.

---

## Suggested order of work

1. **`BASE_TYPE` in `PICL0`/`PICR0`** — highest value. The correct encodings
   likely transfer from `PICL1`/`PICR1`; a two-target Diamond run confirms it.
   Fixes a silent-wrong-answer bug in ECP5 *and* MachXO2 (production).
2. **`SEDGA` in yosys `cells_bb.v`** — smallest fix on this page, and the
   fuzzer data already exists. Coordinate with the SEDGA agent.
3. **Explain the ECP5-vs-MachXO2 D4 asymmetry** — 1459 vs 18 collisions, and
   0 vs 243 round-trip failures. Something structural differs.
4. **`DLLDELD` packer in nextpnr-ecp5** — the one true IOLOGIC-precedent gap,
   following the `c1f89eb` MachXO2 shape.
