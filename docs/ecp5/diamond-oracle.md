# Diamond as an ECP5 oracle

Lattice Diamond is an independent implementation of every stage the open flow
runs. That makes it useful for something more specific than "should we switch":
it can say **where** the open flow loses, so the gap can be closed in yosys or
nextpnr rather than worked around.

## Status

**No utilisation or Fmax comparison was obtained.** What this work produced
instead is the apparatus to obtain one, a measured noise floor that determines
what such a comparison would have to beat to mean anything, four concrete
upstream bugs, and one structural finding that rules out the cleanest
attribution method.

Specifically:

- **The noise floor is measured** on two designs. Utilisation is deterministic
  (spread 0); Fmax varies 2.4-6.8% depending on the design. Any future Fmax
  claim below the per-design figure is not a result.
- **Stage attribution by netlist transplant is impossible** -- yosys and
  Diamond do not share a primitive vocabulary. See
  `docs/diamond-par-isolation-blocked.md`. This is the main negative result and
  it is not a matter of trying harder.
- **Three yosys/Amaranth handoff bugs are fixed and documented** with minimal
  reproducers (`docs/upstream-yosys-edif-notes.md`), re-checkable via
  `./scripts/diamond_probe.py --edif-repro`.
- **Build time already argues against adoption**: Diamond's synthesis alone is
  ~7x the entire open flow.
- **IOLOGIC, the MachXO2 gap, is not the ECP5 gap** -- both flows infer the
  same DDR cells in the same counts.

The one design carried furthest through Diamond (the analyzer) hit a DRC
failure on a byte-enabled memory write port, and the run that did complete
synthesis had its memories destroyed by a `memory_map` mistake on my part,
making its numbers unusable. `vexii_hello` was still in LSE synthesis after
ten minutes when this was written. So the headline question -- does Diamond
pack better -- **remains open**, and this document is the means to answer it
rather than the answer.

This is the same method that produced the nextpnr-machxo2 IOLOGIC work. See
`/mnt/2tb/git/pluribus/docs/upstream-contributions.md` and
`docs/diamond-re-oracle.md` for the MachXO2 precedent.

The target is **LFE5U-12F-8CABGA256** -- 24288 LUT4, 56 DP16KD, 28 MULT18X18D.
That part is the binding constraint on the whole project, so every measurement
uses it; a bigger part would make the numbers meaningless.

## The noise floor comes first

Placement is stochastic. Before any cross-toolchain difference can be called a
finding, we need to know how large a difference the tool produces *against
itself*.

`./scripts/pnr_noise.py` runs one fixed netlist through nextpnr several times
with different seeds. Four seeds each, on two independent designs:

**GSG analyzer** (target 120 MHz):

| metric | min | max | spread |
|---|---|---|---|
| TRELLIS_COMB | 8191 | 8191 | **0** |
| TRELLIS_FF | 2755 | 2755 | **0** |
| DP16KD | 9 | 9 | **0** |
| MULT18X18D | 0 | 0 | **0** |
| Fmax `$glbnet$clk` | 126.25 | 132.80 | **6.55 MHz (5.2%)** |
| Fmax `aux_phy_0__clk__o` | 82.24 | 87.87 | **5.63 MHz (6.8%)** |

**vexii_hello** (target 90 MHz):

| metric | min | max | spread |
|---|---|---|---|
| TRELLIS_COMB | 7257 | 7257 | **0** |
| TRELLIS_FF | 3386 | 3386 | **0** |
| DP16KD | 41 | 41 | **0** |
| MULT18X18D | 4 | 4 | **0** |
| Fmax `$glbnet$clk` | 96.70 | 99.06 | **2.36 MHz (2.4%)** |

Two consequences, and they set the rules for reading everything below:

- **Utilisation is deterministic.** Zero spread on every resource, on both
  designs. Packing does not depend on the seed, so *any* LUT/FF/BRAM
  difference against Diamond is real signal, however small.
- **Fmax is not, and how much it varies depends on the design.** 2.4% on
  vexii_hello, up to 6.8% on the analyzer. So the significance threshold has
  to be measured per design rather than assumed from one -- quoting a single
  global figure would be too strict for one design and too lax for the other.
  This is also why the open-flow numbers were obtained by binary search on
  `--freq` rather than read off one relaxed run, and why any Diamond Fmax must
  come from a constrained run.

The instability is easy to see without the control: `vexii_hello` is quoted at
80.3 MHz in the original brief, its committed `top.tim` reports 97.91 MHz, and
these four seeds span 96.70-99.06 MHz. Three different numbers for the same
design, none of them wrong -- which is exactly why the control had to come
first.

## The three configurations

The comparison is only informative if it can attribute a difference to a stage.
Three runs do that:

| configuration | synthesis | place & route | isolates |
|---|---|---|---|
| open | yosys `synth_ecp5` | nextpnr-ecp5 | baseline |
| `--mode lse` | Diamond LSE | Diamond map/par | whole toolchain |
| `--mode yosys` | yosys `synth_ecp5` | Diamond map/par | **place & route only** |

The third is the one that splits the problem in half. If Diamond wins in `lse`
but not in `yosys`, the gap is synthesis and the fix belongs in yosys. If it
wins in `yosys` too, the gap is in place-and-route and belongs in nextpnr.

## Getting the designs into Diamond

The designs are Amaranth, which normally drives the open flow end to end.
`./scripts/emit_verilog.py` stops it one step earlier and reuses the `.il` that
the open-flow build already wrote, so both toolchains start from
byte-identical RTL. Re-elaborating would risk a different result from a
different library version and quietly invalidate the comparison.

Two forms come out, and each hit a real obstacle worth recording:

**Behavioural** (for LSE). `memory_collect` leaves `$mem_v2` cells that
`write_verilog` emits as instantiations of a module that does not exist.
Diamond stops with

    ERROR - synthesis: logical block 'analyzer/clk_I_0' with type
    'ClockedWritePort_16_1_4095_0_15_0' is unexpanded.

`memory_map` instead lowers each memory to a plain reg array, which is the form
a vendor synthesiser is built to infer block RAM from. This is the correct
comparison -- it lets Diamond apply its own inference rules rather than
inheriting yosys's -- but it does mean **BRAM counts in `lse` mode measure
Diamond's inference, and a low BRAM count there means Diamond declined to
infer, not that the design shrank.** Check DP16KD against the open flow before
reading anything else in that mode.

**EDIF** (for `--mode yosys`). `ngdbuild` reads `.ngo`/`.edif`, not Verilog, so
the structural netlist goes out as EDIF via `write_edif` and in through
`edif2ngd`. Feeding structural Verilog back through LSE would let LSE
re-synthesise it and destroy the separation the mode exists to create.

## Cell-level accounting

Totals hide exactly the thing worth finding. nextpnr reports a single
`TRELLIS_COMB` figure, but the yosys netlists that produced these designs
decompose as:

| primitive | analyzer | vexii_hello |
|---|---|---|
| LUT4 | 5635 | 5505 |
| PFUMX | 900 | 801 |
| CCU2C | 895 | 465 |
| L6MUX21 | 244 | 134 |
| TRELLIS_FF | 2755 | 3386 |
| TRELLIS_DPR16X4 | 22 | 100 |
| TRELLIS_IO | 119 | 66 |
| DP16KD | 9 | 41 |
| MULT18X18D | 0 | 4 |
| ODDRX1F / IDDRX1F | 10 / 9 | 0 / 0 |
| EHXPLLL | 1 | 1 |

If Diamond reaches for hard blocks the open flow ignored -- DSPs, wide LUT
modes, distributed RAM, IOLOGIC -- that is a nameable missing inference in
yosys, and this breakdown is where it shows up.

Note `MULT18X18D`: yosys already infers 4 DSPs in `vexii_hello`, so DSP
inference is not simply absent from the open flow. Whether Diamond finds more
is a question for the comparison rather than an assumption going into it.

**IOLOGIC is not the ECP5 gap it was on MachXO2.** The MachXO2 work found
nextpnr had no IOLOGIC support at all. Here the open flow infers 10 `ODDRX1F`
and 9 `IDDRX1F` on the analyzer, and Diamond's LSE independently reached for
the same class of cells on the same design -- `IDDRX1F` 9, `ODDRX1F` 10, plus
`IFS1P3IX`/`OFS1P3DX`/`OFS1P3IX` register-in-IO variants. The counts match on
the DDR cells. Whatever the ECP5 gap turns out to be, it is not a missing
IOLOGIC implementation, so the MachXO2 fix does not have an obvious analogue
here.

(That observation survives from the discarded `memory_map` run: the memories
in it were destroyed, but the IO cells were untouched by that mistake, and
IO inference does not depend on how memory was expressed.)

**Since the PAR-isolation experiment turned out to be impossible (see
`docs/diamond-par-isolation-blocked.md`), this table is the only attribution
mechanism available.** It can show *that* the flows chose different
primitives; it cannot separate "Synplify/LSE inferred a better structure" from
"Diamond's mapper packed the same structure better". Conclusions drawn from it
should carry that caveat.

## Build time

Measured on the GSG analyzer, same machine, same part:

| stage | open flow | Diamond |
|---|---|---|
| synthesis | ~22 s (yosys) | **303 s** (LSE) |
| place & route | ~20 s (nextpnr) | not reached on this design |
| total | **~42 s** | >303 s |

Diamond's synthesis step alone is roughly **7x the entire open flow**. On
`vexii_hello` LSE synthesis ran longer still, past 5 minutes.

This matters for the framing of the whole question. Even if Diamond packed
meaningfully better, a 7x-plus slower synthesis step would keep it out of an
edit-build-run loop; it could only be justified for release builds. The
open flow's speed is a real advantage that any utilisation gap has to be
weighed against, not a footnote.

## Bitstream options the open flow does not expose

`<diamond>/ispfpga/ep5c00/data/bitgen.usg` documents generator
options absent from `ecppack`: `CfgMode` (Disable/Flowthrough/Bypass), `RamCfg`
(Reset/NoReset), the phase controls `DONEPHASE`/`GOEPHASE`/`GSRPHASE`/
`GWDPHASE`, `ES`, and `-m` for mask and readback files.

Confirmed absent by checking `ecppack` directly rather than taking it on
trust -- none of those option names appear in its strings, and `--help` offers
only `--freq`, `--compress`, `--spimode` and `--bootaddr`.

None of them affect utilisation or Fmax, so they are outside the comparison.
Two are worth noting anyway:

- **`-m` (mask/readback files)** has no open-flow equivalent at all. Readback
  is the basis for verifying a configured device against its bitstream, which
  the open flow currently cannot do.
- **`GSRPHASE`/`DONEPHASE`** control the ordering of global set/reset release
  against DONE. That ordering is exactly the kind of thing that produces a
  design which works from SRAM and fails from flash, so having no control over
  it is a real gap even though it never shows up in a utilisation table.

## Reproducing

    ./scripts/pnr_noise.py --json <top.json> --lpf <top.lpf> --runs 4 --freq 120
    ./scripts/emit_verilog.py --il <top.il> --outdir tmp/diamond/<design>
    ./scripts/diamond_flow.py --verilog <behavioural.v> --lpf <top.lpf> \
        --mode lse --outdir tmp/diamond/<design>_lse
    ./scripts/diamond_flow.py --verilog <structural.edf> --lpf <top.lpf> \
        --mode yosys --outdir tmp/diamond/<design>_yospar

Logs land in `./tmp/logs/`. Diamond's environment is built from scratch inside
`diamond_flow.py` rather than inherited, because the oss-cad-suite environment
the open flow needs sets `PYTHONHOME` and prepends its own libstdc++, which
stops Diamond's engines loading their shared objects.
