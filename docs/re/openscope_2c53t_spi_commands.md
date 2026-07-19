# OpenScope 2C53T (GW1N-2) — the FPGA-side SPI command interface, recovered from the netlist

**Subject:** what the GW1N-2 fabric actually *does* with the SPI port — which commands it
decodes, what each one gates, and what it serialises back on `SO`.
**Method:** full pluribus pipeline lift of the stock 2C53T GW1N-2 bitstream into a relational
netlist, then structural queries via `scripts/gowin_spi_trace.py`.
**Relation:** pluribus issue #70. Builds on the capture-arming cross-check
(`openscope_2c53t_r3_crosscheck.md`, issue #64) and the GOWIN decode fixes in #69.

This is a **static structural recovery**. Everything below is a property of the configuration
bits; nothing was observed on hardware.

---

## TL;DR

| question | answer | confidence |
|---|---|---|
| Command width | **8 bits** — an 8-stage gated shift chain off `SI` | CONFIRMED |
| Opcode field | **5 bits** (chain stages 1-5 latched into a register bank) | CONFIRMED |
| Opcodes decoded | **8 distinct** (`0x01 0x02 0x04 0x05 0x06 0x07 0x08 0x09`) | CONFIRMED |
| Readback on `SO` | 8 latched bits → 3-bit-counter-selected wide mux → `SO` | CONFIRMED |
| Sample data reaches `SO`? | **Yes** — 40 BSRAM `DO` nets reach all 8 mux inputs | CONFIRMED |
| SPI mode 0 vs 3 | **Not decidable — and moot.** Both sample on the rising edge | CONFIRMED |

Two results are worth flagging up front.

**The readback path is no longer a gap.** The prior cross-check recorded "BRAM → `SO`" as
NOT VERIFIABLE, because `SO`'s drive net had no modelled driver. The cause is now identified:
`SO` is driven by wire `R17C12_OF5`, which is the output of a GW1N **wide-mux**
(`MUX2_LUT5/6/7/8`) — a bel class pluribus does not lift as a cell, so the datapath silently
dead-ended. Reconstructing that mux chain from the routing arcs recovers the entire output
multiplexer.

**The opcode decode is only 5 bits wide.** No decode anywhere in the design tests command
bits 5-7. Every opcode therefore **aliases modulo 32** — the fabric cannot distinguish `0x01`
from `0x21` or `0x41`. Any host-side command numbering above `0x1F` collapses onto these same
decodes.

---

## 1. What was lifted

Stock 2C53T GW1N-2 bitstream (IDCODE `0x0120681B`), carved from the device application image
and trimmed to its true length (115,638 B), converted to an apicula `.fs`, then:

```
gowin_unpack.py --device GW1N-2
load.py --lifter gowin --device GW1N-2
reach.py -> reach2 -> reach3 -> reach4 -> auto_name -> patterns -> report
```

| | |
|---|---|
| tiles configured | 317 |
| routing arcs | 37,224 |
| LUT4 / flops / ALU | 847 / 1,416 / 192 |
| BSRAM | 4 blocks, 840 ports (816 routed) |
| nets | 5,359 |

Of the 1,416 flops only **686 are genuinely clocked**; the remaining 730 sit in default fuse
state with `CLK` tied to a constant. All capture-engine findings of the earlier cross-check
reproduce exactly on this fresh build (CH1 `CEA` gate `INIT=0x3300`, CH2 `0x0f00`, the shared
registered `CEA` on two channels, and the re-arm AND `lut_r5c15_LUT7` `INIT=0x8000`).

> **Package / pin numbering — and why it does not matter here.** No apicula package table is
> correct for this part (a `GW1N-UV2` in vendor package **QN48**): `LQFP100` is a physically
> different package and `QFN48X` is a different part on a different die, agreeing with the
> vendor QFN48 table on **0 of 35** overlapping pins. The board therefore declares no package
> (issue #73), and **no apicula-derived pin number is cited in this document**.
>
> This costs the analysis nothing, and that is verifiable rather than asserted: building the
> netlist under `LQFP100` and under `QFN48X` yields **identical** `ffs` (1,416), `luts` (847),
> `alu_cells` (192), `ebr_ports` (840) and `arcs` (37,224) tables, and identical net IDs for
> all four SPI pads. The package selection affects only `pad_map` pin numbers, which nothing
> below uses — pads are identified by IOB **location name**, which is package-independent.
> Where a physical pin *is* quoted (§2) it comes from the **vendor** IDE device table
> (`GW1N-2/QFN48`), which is authoritative for this part; ingesting it is issue #74.
>
> One practical note: `load.py` currently *requires* a package, so with the board's package
> unset the board-driven pipeline (`--board boards/fnirsi-gw1n2`) aborts with
> `FATAL: board.toml missing [board] package`. Until #74 lands, pass an explicit
> `--package` for the load step; per the equivalence above, which one is immaterial.

---

## 2. The SPI pads

The four SPI pads are the GW1N-2's own **dedicated SSPI configuration pins**, reused by the
design as its runtime slave port. The vendor package table names them outright in its `CFG`
column — an identification that is independent of anything in the netlist:

(Pin numbers below are **vendor** QFN48 values, not apicula's — see the note in §1.)

| signal | IOB location | vendor `CFG` | vendor pin | fabric reach |
|---|---|---|---|---|
| SCLK | `IOB5A` | `SCLK` | 29 | routes to `R19C10_CLK1`, **no modelled consumer** |
| SO | `IOB5B` | `SO` | 28 | driven from `R17C12_OF5` (wide mux) — recovered, §6 |
| CS_N | `IOB18A` | `SSPI_CS_N` | 34 | routes to `R19C20_CLK2`, **no modelled consumer** |
| SI | `IOB18B` | `SI` | 35 | **one** consumer: `lut_r15c8_LUT3` |

Two independent RE directions agreeing on pad roles is worth stating plainly: the upstream
project assigned these roles by inference from fabric behaviour, and the vendor's own
configuration-pin table assigns the same roles by name.

`SI` is the *only* one of the four that reaches modelled fabric logic. `SCLK` and `CS_N` both
terminate on **IO-row tile clock wires**, i.e. they are injected into the clock tree. There is
no `IOLOGIC` block on the bottom edge (all 16 decoded `IOLOGIC` instances sit on the left and
right edges), so nothing consumes them in the lifted netlist. This is the same decode gap the
earlier cross-check recorded as gap 5, now localised precisely.

---

## 3. The input shift register — command width is 8 bits

`SI` enters at `lut_r15c8_LUT3` (`INIT=0xa0a0`, `A & C`): the serial bit ANDed with a shift
enable (`n2076`). From there an 8-stage chain, every stage the same `prev_Q & enable` form:

| stage | flop | Q | via LUT | function |
|---|---|---|---|---|
| 1 | `ff_r15c8_DFF3` | `n1821` | `lut_r15c8_LUT3` | `SI & en` |
| 2 | `ff_r15c7_DFF0` | `n1902` | `lut_r15c7_LUT0` | `q1 & en` |
| 3 | `ff_r15c7_DFF1` | `n2003` | `lut_r15c7_LUT1` | `q2 & en` |
| 4 | `ff_r15c7_DFF2` | `n1904` | `lut_r15c7_LUT2` | `q3 & en` |
| 5 | `ff_r15c7_DFF3` | `n1908` | `lut_r15c7_LUT3` | `q4 & en` |
| 6 | `ff_r15c7_DFF4` | `n2005` | `lut_r15c7_LUT4` | `q5 & en` |
| 7 | `ff_r15c7_DFF5` | `n1917` | `lut_r15c7_LUT5` | `q6 & en` |
| 8 | `ff_r15c8_DFF4` | `n1918` | `lut_r15c8_LUT4` | `q7 & en` |

All eight are `DFFC` sharing one clock (`n3527`/`n3528`) and one async clear. The chain ends
at stage 8 — nothing extends it. **Command width = 8 bits.** CONFIRMED.

Note this is *not* what `api.Netlist.shift_registers()` reports: `reach3`'s detector requires
successive flops to share `CLK` **and** `CE` nets and to connect `Q`→`D` directly. Here every
stage passes through an enable LUT, and the GOWIN clock spine is not unified (§8), so the
detector finds no chains at all. `gowin_spi_trace.py` recovers the chain by following the
shared enable term instead.

---

## 4. Command register and bit ordering

Several banks latch the chain in parallel; each bank's bits share one real clock-enable:

| bank load CE | bits | chain stages | role |
|---|---|---|---|
| `n2156` | 5 | 1-5 | **the opcode register** |
| `n2114` | 8 | 1-8 | data register (whole received byte) |
| `n2105` | 5 | 1-5 | data register |
| `n2018` | 2 | 1-2 | data register |
| `n2009`, `n2014` | 1 | 1 | single-bit data registers |

The `n2156` bank is the opcode register: `ff_r15c10_DFF2/DFF4` and `ff_r15c9_DFF0/DFF1/DFF2`,
fed from stages 1-5. Its sibling flops `ff_r15c9_DFF3`, `ff_r15c10_DFF3/DFF5` are *not* opcode
bits — they latch derived values, and two of them have no consumers at all.

**Bit ordering is established from the netlist, not assumed.** The `n2114` bank is the only
one that latches all 8 stages, and its outputs drive the `i1` inputs of two mode-9 ALU chains.
Stage number maps *monotonically onto ALU bit index*:

```
stage 1 -> n7  -> alu_r2c7_1.i1     (low)
stage 2 -> n10 -> alu_r2c7_2.i1
...
stage 8 -> n29 -> alu_r2c8_2.i1     (high)
```

So the last bit clocked in (stage 1) is the arithmetic **LSB** — which is exactly MSB-first SPI
framing. Opcode bit *k* = chain stage *k+1*. The numeric opcodes below follow from that.

---

## 5. Opcode → decoded enable → effect

Thirteen nets in the design are pure AND-minterms over the opcode register. Nine are full
5-bit matches (`mask=0x1f`, unambiguous within `0x00`-`0x1F`); four are partial decodes with a
don't-care bit, so they match two opcodes each.

| opcode | enable net | mask | gates | effect | confidence |
|---|---|---|---|---|---|
| **0x01** | `n2105` | `0x1f` | 8 CE | Latches stages 1-5 into an 8-flop bank (`r12c7`/`r13c7`/`r14c8`); feeds local compare LUTs `lut_r12c7_*`, `lut_r12c8_*` | decode+target **CONFIRMED**; analog meaning *unknown* |
| **0x02** | `n2018` | `0x1f` | 2 CE | Latches stages 1-2 into `ff_r13c7_DFF2/3` → `lut_r13c5_LUT0/1`. Shortest path of any opcode to the BSRAM write enables (8 hops) | decode+target **CONFIRMED**; role INFERRED |
| **0x04** | `n2119`, `n2147` | `0x1f` | 0 CE | Consumed only as LUT inputs in the `r15c11`-`r15c14` control block | decode **CONFIRMED**; effect **INFERRED** |
| **0x05** | `n2121`, `n2123` | `0x1f` | 0 CE | `n2123` drives `ff_r15c11_DFF3.D`; neither gates a CE | decode **CONFIRMED**; effect **INFERRED** |
| **0x06** | `n2014` | `0x1f` | 2 CE | Latches stage 1 into `ff_r14c8_DFF2/3`. `ff_r14c8_DFF2` (`n908`) broadcasts to 8 LUTs across the capture front end — a global mode bit | decode+fanout **CONFIRMED** |
| **0x07** | `n2009` | `0x1f` | 2 CE | Latches stage 1 into `ff_r14c8_DFF0/1`. Shortest path to the shared BSRAM `CEA` and to the data-ready pad `IOR13A` (7 hops each) | decode+target **CONFIRMED**; *arming* role **INFERRED** from proximity |
| **0x08** | `n2114` | `0x1f` | 8 CE | The only full-byte load: all 8 stages → `ff_r13c8_DFF0-5` + `ff_r14c7_DFF0/1` → `i1` of two ALU chains. A comparison/threshold value | decode+target+ALU **CONFIRMED** |
| **0x09** | `n2112` | `0x1b` | 0 CE | Partial decode (bit 2 don't-care) — also matches `0x0d`. Drives `ff_r15c10_DFF5.D` | decode **CONFIRMED**; effect **INFERRED** |

Partial decodes `n2012` (`0x06`, mask `0x1e`), `n2021` (`0x02`, mask `0x1e`) and `n2113`
(`0x08`, mask `0x1c`) are intermediate terms feeding the full decodes above.

**On "effect" claims.** What is CONFIRMED is *structural*: opcode X asserts enable net N, which
gates the clock-enable of a specific named flop bank, whose outputs drive specific named
consumers. What is NOT established is the physical meaning (which analog parameter, what units,
what encoding) — a static netlist does not carry that. Where the table names a role such as
"arming" or "threshold", that is an inference from what the register feeds, labelled as such.

Opcodes `0x01`, `0x02`, `0x06` and `0x07` all reach every BSRAM `CEA`, the data-ready output and
the 8-flop async re-arm net `n1075` (driven by the 4-input AND `lut_r5c15_LUT7` — the same
re-arm gate the earlier cross-check identified). **`0x08` reaches none of them**, which is
consistent with it being a pure datapath register rather than a control command.

**No opcode decode drives a BSRAM control port or an async set/reset directly.** Register
writes are the only mechanism; the capture engine is influenced through the state those
registers hold, never by a command line straight into the memory.

---

## 6. The readback path onto `SO`

`SO` (`IOB5B`) is driven by tile wire `R17C12_OF5`. In apicula's tile model the `OF0`-`OF7`
wires are the **wide-mux chain** (`MUX2_LUT5/6/7/8`), which pluribus does not lift as cells —
hence "no modelled driver" and the earlier NOT VERIFIABLE verdict. Rebuilt from the arcs:

```
OF5 = MUX2_LUT61(sel n2173) ? OF4 : OF6
  OF4 = MUX2_LUT52(sel n2170) ? F5 : F4
  OF6 = MUX2_LUT53(sel n2170) ? F7 : F6
```

and each of `F4`-`F7` is itself a 2:1 mux LUT (`lut_r16c11_LUT4..7`) selected by a common net
`n2172`. Net: an **8:1 multiplexer** over eight latched bits, with a 3-bit select.

The three select bits `n2173`/`n2170`/`n2172` are the outputs of `ff_r16c10_DFF0/DFF1/DFF2` — a
3-bit counter (`DFF2` toggles, `DFF1` is its XOR, `DFF0` completes the count). So `SO` is
serialised by *counting through* eight parallel bits, not by shifting them. Corroborating this,
`lut_r16c11_LUT1` (`INIT=0xC000`, `B & C & D`) decodes select `== 7`, the end-of-byte marker.

The eight data bits are `DLC` latches in tiles `r14c11`, `r14c12` and `r16c11`, all sharing one
load enable `n2203` (itself a minterm over the select counter and `ff_r16c12_DFF0/1/2`). Each
latch takes its `D` through a buffer LUT from a `DFFC` flop — an 8-bit parallel capture, then
serialise.

**Sample data does reach `SO`.** 40 distinct BSRAM `DO` nets reach all eight mux data inputs and
all eight latch `D` inputs. Reachability is transitive and so does not by itself prove a direct
datapath, but combined with the recovered mux structure the conclusion is solid: the readback
serialises captured sample data out of the BSRAMs. This closes cross-check gap 3.

---

## 7. The SPI mode question — settled, by being dissolved

The host-side documentation records the MCU's SPI3 configuration as **disputed**: Mode 0 in one
source, Mode 3 in another, "not resolvable statically" from the firmware.

The netlist gives a clean, checkable fact:

> **Every sequential element in the design is positive-edge triggered.** The flop census is
> `DFF 574, DFFS 493, DFFC 148, DFFR 147, DLC 26, DL 18, DFFP 10` — **zero** `DFFN*`.

This is positive evidence, not an artefact of missing decode: both apicula and pluribus's own
GOWIN unpacker carry the full negative-edge table (`DFFN`, `DFFNC`, `DFFNR`, `DFFNP`, `DFFNS`),
so a negative-edge flop *would* have been lifted as one. The fabric samples on the **rising**
edge.

**That does not discriminate Mode 0 from Mode 3 — because nothing could.** Mode 0 (CPOL=0,
CPHA=0) samples on the leading edge, which with CPOL=0 is the rising edge. Mode 3 (CPOL=1,
CPHA=1) samples on the trailing edge, which with CPOL=1 is *also* the rising edge. The two modes
differ only in **CPOL**, the idle level of `SCLK` — a property of the master and the board, with
no representation anywhere in a slave's logic.

So the verdict is:

- **Not determinable from the netlist** that the FPGA is "Mode 0" or "Mode 3", and no amount of
  further decode work would change that.
- **The question is malformed for a slave.** A rising-edge-sampling slave is compatible with
  *both* modes. That is almost certainly *why* the two sources disagree and why the firmware
  analysis found it unresolvable: both readings work, so both got written down.
- The actionable statement for anyone driving this device: **clock it so data is sampled on the
  rising edge** (Mode 0 or Mode 3, freely).

One caveat, stated explicitly: this assumes the shift chain is clocked by `SCLK` itself. The
chain's clock is global spine `GB00`, whose origin is not decoded (§8), so pluribus cannot
*prove* `GB00` carries `SCLK`. If the chain were instead clocked by an internal clock and `SI`
oversampled, the edge argument would concern that clock. The rising-edge finding holds either
way; what is unproven is which clock it applies to.

---

## 8. Decode gaps encountered

These are engine limitations, stated precisely so they can be closed or worked around.

**Gap A — the GW1N wide-mux (`MUX2_LUT5/6/7/8`) is not lifted.** pluribus lifts LUT4, DFF, ALU
and BSRAM; the per-tile wide-mux chain is absent. Any net driven by an `OF` wire therefore has
no modelled driver and traces through it dead-end silently. This is what made the readback path
unverifiable. Only one `OF` wire is in use in this design, so the impact here was one datapath —
but a design leaning on wide muxes would be badly mis-recovered. `gowin_spi_trace.py` §5
reconstructs the chain externally; lifting it properly is the real fix.

**Gap B — the clock spine is not resolved.** All 185 distinct flop clock nets have **zero**
modelled drivers, and none is reachable from any pad. Global spine nets (`GBxx`) surface as
independent domains. Consequences: shift-register detection by `CLK`+`CE` equality cannot work
on GOWIN, and no clock can be tied back to its source pad — which is the one thing that would
have let §7 prove `SCLK` clocks the chain.

**Gap C — `SCLK`/`CS_N` reach no modelled cell.** Both land on IO-row tile clock wires. `CS_N`
having no fabric consumer is a genuine finding (it matches upstream); `SCLK` is a decode gap
downstream of Gap B.

**Gap D — ALU sum outputs are not modelled.** Every `alu_cells` row has `sum_net = NULL`; only
the carry nets are present. The `0x08` threshold register's connection to ALU `i1` is solid, but
what the ALU *computes* with it is not traceable.

**Gap E — 51 of 685 real flop `D` nets, and 567 of 3,238 non-constant LUT inputs, have no
modelled driver.** Some of this is Gap A and Gap B; the remainder is unaudited.

---

## 9. Cross-reference against the host side

The brief for this work anticipated a host-side command set of roughly 40 commands spanning
`0x00`-`0x2C`, recovered from firmware, to check against. **That list could not be located for
this device**, and the discrepancy is itself worth recording:

- The 2C53T firmware notes describe **SPI3** as the FPGA *config/cal write + ADC sample read*
  path, and a **separate USART2 link** (9600 8N1, 12-byte magic-framed messages) as the FPGA
  command/status bus. A ~40-command control vocabulary would belong to that serial bus, not to
  the SPI port analysed here.
- The `0x00`-`0x2C`-shaped register map that does exist in this repo belongs to a **different
  board and vendor** (a MachXO2-based instrument), and is not applicable to the 2C53T.
- The 2C53T firmware notes state plainly that the SPI opcodes are "only visible as bytes — their
  FPGA-side effect needs dynamic capture", and name a bitstream decode as the handoff. This
  document is that handoff completed: the effects were recovered statically after all.

**Where the two directions do meet, they agree.** The firmware describes SPI3 as carrying
calibration/config writes plus sample readback. The netlist shows exactly that shape: a register
write interface (opcode selects a target register, subsequent bits supply its value) plus a
sample-data readback serialiser fed from the capture BSRAMs. There is no general-purpose command
processor on this port — no opcode reaches a BSRAM control line or an async reset directly.

**One concrete disagreement risk to flag:** because the fabric decodes only 5 opcode bits, any
host command numbering that relies on bits 5-7 to distinguish commands would be **silently
aliased** by this FPGA. A host sending `0x21` gets the `0x01` behaviour. If a host-side list
spanning `0x00`-`0x2C` does exist, the commands at `0x20`-`0x2C` are worth re-examining on
hardware for exactly this reason.

---

## 10. Reproducing

```
# decode + lift + analyse (python3.15t throughout).
# --package is required by load.py but immaterial to every result below (see §1);
# it is dropped entirely once the vendor QFN48 table is ingested (#74).
gowin_unpack.py scope.fs scope.gwconfig --device GW1N-2
load.py --label LBL --config scope.gwconfig --pins pins.tsv \
    --lifter gowin --device GW1N-2 --package LQFP100
reach.py --bitstream LBL      # then reach2/3/4, auto_name, patterns, report

# the SPI command-interface trace
scripts/gowin_spi_trace.py --bitstream LBL --si-pad IOB18B

# import the recovered map so it is queryable
annotate.py --bitstream LBL --board boards/fnirsi-gw1n2
```

Then via the API:

```python
import api
nl = api.Netlist("LBL")
nl.spi_regs()                      # the recovered opcode map
nl.spi_reg(0x08, bank="OPCODE")    # WR_THRESHOLD
```

`scripts/gowin_spi_trace.py` is board-agnostic: given a serial-input pad it recovers the shift
chain, the chain-fed register banks, the minterm opcode decodes, the wide-mux readback path and
the edge-sensitivity census for any GOWIN design.
