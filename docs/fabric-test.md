# Fabric self-test: is this die actually good?

A suite of self-checking bitstreams anyone can flash onto their own board to get
a broad answer. Tracked as [#101](https://github.com/awtoau/pluribus/issues/101).

## Why this exists

Nothing in the open flow tests fabric **function**:

- **SED/SEDGA is not this.** It CRCs the *configuration memory* — it catches a
  flipped config bit, not a dead LUT or a broken wire.
- **Vendor test** uses proprietary vectors at wafer/package and is not
  user-accessible. It is also the process that would have binned a part.
- **Off-the-shelf for ECP5**: nothing we are aware of.

The question became concrete with [#98](https://github.com/awtoau/pluribus/issues/98):
`LFE5U-12F` and `-25F` are the same die, and the open flow gives a 12F all 24,288
LUTs unpatched. That extra fabric worked on the one part tested, but
binning/salvage is only *bounded*, not excluded — so "does my die work?" is a
real question with no tool to answer it.

## What it is and is not

**Is:** a confidence check. Flash N bitstreams, read a signature back over JTAG,
get a per-test pass/fail and a cumulative coverage figure.

**Is not:** a proof. Coverage is counted per tile *type*, not per instance —
every PLC2 shares one mux structure — so this asks "does this fabric broadly
work", not "is every instance good". A hard defect in one specific tile can hide.

And as #98 established: one part, one operating point, one moment. A pass does
not generalise to another chip, temperature, or supply corner.

## How many bitstreams

Coverage is bounded by **mux fan-in**: a PIP is a mux selection, so one source
per destination per configuration. That exclusion is the *only* thing forcing
extra bitstreams — bel pins and wires ride along in parallel.

```
python3 scripts/fabric_coverage_plan.py --device LFE5U-12F
```

| bitstreams | ECP5 `LFE5U-12F` | MachXO2 `LCMXO2-1200` |
|---:|---:|---:|
| 8 | 40.3% | — |
| 16 | 75.7% | — |
| **24** | **97.0%** | **99.3%** |
| 64 | 100.0% | — |

**24 is the knee.** The last 3% costs another 40 bitstreams, because p95 fan-in
is 24 on both families while the maximum is 64 — the tail is a handful of very
wide muxes. Pick a point on that curve knowingly; the tool prints it.

## Usage

### 1. Generate

```
python3 scripts/fabric_test_gen.py --device LFE5U-12F --count 24
```

Writes `tmp/fabric-tests/LFE5U-12F/fabric_test_NN.v` plus `manifest.tsv`
recording each design's seed and expected signature.

### 2. Verify in simulation — before touching hardware

```
python3 scripts/fabric_test_verify.py --dir tmp/fabric-tests/LFE5U-12F
```

A design that cannot pass against a perfect simulated fabric will never pass on
silicon, and debugging that on a board wastes the trip.

It also prints synthesised cell counts. Check the flip-flop count is near
`32 × blocks`: if it is near 32, yosys deduped the blocks and the "N parallel
blocks" are illusory.

### 3. Run the negative control — do not skip this

```
python3 scripts/fabric_test_gen.py --device NEGCTL --count 4 --negative-control
python3 scripts/fabric_test_verify.py --dir tmp/fabric-tests/NEGCTL --expect-fail
```

Same designs, one bit wrong in the golden. **Every test must FAIL.** Without
this, a clean hardware run proves only that the detector is silent — which is
also what a *broken* detector looks like. #98's result rests on exactly this
step.

### 4. Build and flash

```
yosys -p "synth_ecp5 -top fabric_test_00 -json ft00.json" fabric_test_00.v
nextpnr-ecp5 --12k --json ft00.json --textcfg ft00.config --lpf <your board>.lpf
ecppack ft00.config ft00.bit
```

Load **volatile** (SRAM) rather than writing flash, so a bad build cannot brick
the board.

### 5. Read the result

**The generator does not build a JTAG readout.** Its designs expose the
signature and status as ordinary ports. Use the path that has already run on
silicon — #98's Amaranth gateware over LUNA's `JTAGRegisterInterface`, which
managed 2,002 clean rounds on a Cynthion r1.4 with a control reporting
1,575/1,575 mismatches.

```
python3 scripts/fabric_test_bridge.py --manifest tmp/fabric-tests/<dev>/manifest.tsv
```

That prints the `fabric_build.py` invocations realising the plan. It prints
rather than runs them: the build tooling lives in another repo with its own
toolchain, and a script that silently shells into a sibling checkout is harder
to audit.

> **Golden values are not portable between recurrences.** This generator uses a
> plain Galois LFSR; #98's gateware adds a nonlinear mix
> (`rotl(3)&rotl(17)`, `rotl(11)|rotl(29)`) and so produces *different*
> signatures from the same seeds. Handing a golden computed here to that
> gateware makes every round mismatch — which looks exactly like a dead fabric.
> The bridge therefore does **not** pass `--golden` unless you ask; let the
> build compute its own, and take only the count, blocks and round size from the
> plan.

Report cumulatively, e.g. `18/24 passed — 91% of routing arcs exercised`. A user
who runs 6 of 24 has ~40%, not an unqualified "pass".

## Why JTAG rather than pins or SPI

**JTAG is the only channel guaranteed to exist** — it is how the bitstream
arrives, so anyone who can run the test can already read it back. No extra
wiring, no host MCU, no board knowledge.

It also makes the suite **portable across devices, not just boards**: the
signature register is fabric logic needing no bonded I/O, so it fits a small
part as readily as a large one. Only the *number* of bitstreams changes with
device size, since that is set by fan-in.

**LEDs cannot be the verdict.** Which pin reaches an LED is a *board* fact.
Bonded pin counts vary **98–197 across packages of a single ECP5 part**, so a
pad-based readout would need a per-package variant. Use LEDs as a local
convenience if you like — `pass` and `done` are brought out for exactly that —
but the JTAG register is the evidence. In #98 the LED liveness walk had a bug
that made it briefly *mimic* the wedged state it existed to detect; harmless
there because JTAG carried the result, a false negative if it had not.

**SPI is worse** — a host MCU, wiring and an agreed protocol, i.e. a
board-integration project per user.

## How a test works

Each design fills the fabric with independent LFSR blocks, runs a fixed number
of cycles, and XOR-folds every block's state into a 32-bit signature compared
against a golden baked in at build time.

Three properties make that a measurement rather than a formality:

- **The golden is computed independently.** `fabric_test_gen.golden()` runs the
  same recurrence in Python; the Verilog implements the same shift/xor. One
  definition, two consumers, so a gateware bug and an expectation bug cannot
  cancel.
- **Blocks use distinct polynomials and seeds** — otherwise yosys dedupes them.
- **Every block reaches the signature** — otherwise yosys prunes it.

Synthesis of one 12-block design: `TRELLIS_FF=419  LUT4=227  CCU2C=16
PFUMX=12  L6MUX21=3`. Note it exercises carry chains and wide muxes, not just
LUTs and flops.

## Known gaps

- **The 18% a PIP sweep misses.** Of ECP5's 1,106,196 wires, 203,948 have no
  uphill PIP — bel-driven outputs and tile-boundary aliases. A pure PIP sweep
  would report "all PIPs covered" having missed nearly a fifth of the wiring.
- **The coverage figure is a plan, not a measurement.** `fabric_coverage_plan.py`
  reports what a *perfect* packer would reach. These designs do not yet place
  against that plan, so the achieved figure is unmeasured and will be lower.
- **Type coverage is a separate axis.** EBR, DSP, PLL, DCC, DQS, SERDES and EFB
  are distinct tile types. A slice sweep says nothing about them.
- **Intermittent defects need a soak.** A single pass cannot measure a rate;
  #98 bounds it at ≤1.4 × 10⁻⁴ per round at one operating point.
