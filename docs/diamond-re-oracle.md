# Diamond as a reverse-engineering oracle

## The principle

When pluribus (via prjtrellis) can't recover something from a vendor
bitstream, the reflex is to reverse-engineer the gap out of prjtrellis's
incomplete model — chase the routing by hand, patch `gkey()`, guess the
EFB port names.  That is usually the wrong tool, and it is how you
introduce silent regressions in the core canonicalizer.

The right tool: **the design was authored in Lattice Diamond, so build a
reference design in Diamond and read the answer out of it.**  Diamond is
ground truth — it produces the same class of bitstream the vendor did.
Two ways to read the answer out:

- **Diamond's PAR report** names the routing prjtrellis records only
  partially (long-line taps, config-corner entry).  `diamond_lattice.md`
  already uses this for H06E bus taps: *"prjtrellis records only the
  source arc (JQ→H06E); Diamond fills the gap."*
- **Recover-and-compare**: build a design whose behaviour you control,
  unpack it, run it through pluribus, and compare its recovered netlist
  to the target.  Because you chose the design, you know the answer, so
  you learn the *encoding pattern* — then find that pattern in the target.

See also [diamond_lattice.md](diamond_lattice.md) for the batch flow
(install, `diamondc` TCL, `ecpunpack`) and the `diamond-fuzz/`
infrastructure (1781 targets, `gen_fuzz_targets.py`, `parse_results.py`,
the ~1.4 GB fuzz DB).

## Decision framework — when to reach for Diamond

Reach for the oracle when:

- **Routing is recorded incompletely by prjtrellis** — long-line
  (H06E/H06W/V06…) *taps* (prjtrellis stores the source arc, not the
  downstream pickups), or signals that enter the fabric through the
  **config corner** (sysCONFIG slave-SPI, JTAG-ER) rather than a normal
  PIO.  Symptom: a net that "dead-ends" or a pad that reads
  `conn=fabric fan=0 dead` even though it is clearly used.
- **A hard-IP interface isn't decoded** — the EFB (WISHBONE / hardened
  SPI / I2C / timer / UFM) and the PLL config.  prjtrellis knows the
  block is *enabled* but not its internal port wiring.
- **A known logical function has an unknown encoding** — e.g. a hardcoded
  readback value muxed onto a bus.  Build it with a *known* value and
  learn how Diamond lays it out.

Do **not** reach for it when:

- pluribus already recovers the thing cleanly (most fabric logic — LUTs,
  FFs, ordinary routing — is fully recovered; don't rebuild it).
- The gap is a genuine pluribus bug in code we own (parsing, DSU,
  net-naming) — fix that directly.

The test: *is the missing information about how the silicon/toolchain
encodes something (→ oracle), or about our own processing of data we
already have (→ fix the code)?*

## The three strategies

### 1. Routing / config-corner fuzz — PAR report as ground truth

Build a MachXO2 design that exercises the routing prjtrellis under-records,
route + PAR in Diamond, and read the tap/entry wiring from the PAR report
(or diff the unpacked `.config` against a baseline).

Canonical open case: **sysCONFIG slave-SPI → user fabric.**  Every
existing `diamond-fuzz` SPI target is *EFB*-SPI (the hardened peripheral);
none route the sysCONFIG slave-SPI port into fabric logic — which is what
a soft SPI register interface actually uses, and why its input pads read
`fan=0 dead`.  A target that enables the slave-SPI config port and wires
it to a fabric shift register would expose the config-corner arcs and
teach the lifter to trace SPI pins into the fabric.

### 2. Synthesize-and-compare — known-answer recovery

Write Verilog for the function of interest with a **known** answer, build
it in Diamond, recover it through pluribus, and learn the structural
pattern the toolchain emits.  Then locate that pattern in the target and
read off the target's actual values.

Placement varies run-to-run, so match on **topology** (LUT-INIT patterns,
mux shape, FSM structure), not location.  The payoff is that you never
have to fully trace the target's front-end — you only have to *recognise*
the encoding you already characterised.

### 3. Full re-implementation — validation by rebuild

When a subsystem's behaviour is fully known from another source (e.g. the
SPI register map from firmware RE), rebuild an equivalent in Diamond,
recover it, and structurally align it to the target.  Proves out the
whole subsystem's recovery, not one value.

## Worked example — the REG 0x05 ident (see the split below)

The 8-byte identification read (`[0xa0][0x05][0xa0] → 8 bytes`) is served
by a **soft fabric SPI decoder** — MOSI/CLK/CS enter via the config
corner, feed a ~50-FF shift register, and a byte-select mux drives the
readback.  pluribus can't statically read the 8 values because (a) the
config-corner entry routing isn't modelled and (b) the byte-select mux
rides long-lines whose taps prjtrellis doesn't record.  Both are oracle
problems, not code bugs:

- Strategy 1 recovers the config-corner entry (→ trace SPI pins to the
  shift register).
- Strategy 2 with a *known* ident teaches us how Diamond encodes
  "hardcoded byte → SPI readback mux"; we then read the target's real bytes.

This is the correct path.  The session that discovered this first tried
to hand-patch `gkey()` to recover the long-line taps and regressed the
canonicalizer — exactly the mistake this doc exists to prevent.

## Generic vs project-specific

Pluribus is a board-agnostic engine ([boards/README.md](../boards/README.md)).
The **methodology and the tooling gaps it closes are generic** and mostly
belong upstream; the **recovered facts about one board's design are
specific** and belong with that board's RE project (the downstream board
project that consumes the engine).
The rule of thumb: *the method to recover any X is generic; the value of
this board's X is specific.*

| Item | Generic / upstreamable | Where it lands |
|---|---|---|
| "Diamond as RE oracle" methodology + the three strategies | **generic** | this doc (pluribus) |
| `diamond-fuzz` harness (`gen_fuzz_targets`, `parse_results`, run infra) | **generic** | pluribus |
| sysCONFIG slave-SPI → fabric config-corner routing encoding | **generic** | prjtrellis bit DB + lifter (benefits any soft-SPI MachXO2 design) |
| EFB WISHBONE / hardened-SPI / I2C / timer / UFM port + fixed-conn decode | **generic** | prjtrellis + lifter (fixes the `EFB_JF` guess for every EFB user) |
| Long-line (H06E/V06/…) tap recovery (pad-fanout gap, mode A/B) | **generic** | prjtrellis / lifter routing model |
| IOLOGIC (`IDDRXE`/`ODDRXE`/…) mode encodings | **generic** | prjcombine → nextpnr-machxo2 (tracked: pluribus#19) |
| EFB support in nextpnr-machxo2 | **generic** | nextpnr (already contributed) |
| — | — | — |
| The 8-byte REG 0x05 **ident values** and their meaning | **specific** | the board project (`fpga-spi.md` §REG 0x05) |
| The SPI register map (0x00–0x1e: front-end, trigger, DAC, AWG, timebase) | **specific** | the board project (`fpga-spi.md`) |
| Which fabric logic is *this board's* soft SPI decoder / ident mux | **specific** | the board project |
| ADC/DAC/AFE pin assignments, shift-register wiring | **specific** | `boards/<board>/` + the board project |
| Per-model bandwidth/timebase behaviour, calibration flow | **specific** | the board project |

Note the useful pairing: recovering *this board's* ident (specific) is
what forces us to close the config-corner-SPI and EFB decode gaps
(generic, upstreamable).  A board's RE need is the forcing function; the
engine improvement it drives should be written so the next board — and
upstream — gets it for free.

## Upstream contribution path

Generic encodings extracted via the oracle should flow to the open-source
MachXO2 stack rather than staying in the lifter as hand-authored maps
(the `EFB_JF` guess is the anti-pattern):

1. Extract the bit/routing encoding for the feature (Diamond build → diff).
2. Add it to the prjtrellis database (or prjcombine device model for
   IOLOGIC), with a check-suite entry.
3. The lifter then reads authoritative data instead of guessing.

Tracked under pluribus#19 (prjtrellis check suite, nextpnr-machxo2
IOLOGIC, prjcombine MachXO2).  Per project rules, never push to upstream
remotes without explicit sign-off.
