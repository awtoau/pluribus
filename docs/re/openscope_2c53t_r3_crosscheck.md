# OpenScope 2C53T (GW1N-2) — independent cross-check of the R3 capture-arming trace

**Subject:** DavidClawson's `OpenScope-2C53T` R3 analysis, "what arms / sustains scope
capture", plus its follow-up (`R3_FOLLOWUP2`).
**Method:** full pluribus pipeline lift of the stock FNIRSI 2C53T GW1N-2 bitstream into a
relational netlist, then structural queries against the DB.
**Relation:** pluribus issue #64 (evaluating what pluribus can contribute upstream).
This is a **local, independent reproduction**. Nothing here was pushed to the OpenScope
project.

The upstream analysis was a hand-trace over apicula's emitted Verilog
(`gowin_unpack -o`). This cross-check is independent in its input path as well as its
tooling: the bitstream was carved from the device firmware and converted to `.fs` locally,
then decoded, lifted, and queried through pluribus. The two paths share only the apicula
chip database.

---

## TL;DR

Of the four headline R3 claims plus four checkable follow-up claims:

| | count | |
|---|---|---|
| **CONFIRMED** | 6 | including three exact cell-level bullseyes |
| **REFUTED / corrected** | 2 | CE-gate uniformity; fan-out counts are depth-bounded, not closure |
| **EXTENDED** | 5 | read port resolved, cone set-identity proven, per-channel INITs differ |
| **NOT VERIFIABLE (decode gap)** | 2 | BRAM→SO readback path; SPI register clock source |

The upstream model is **substantially correct**. The capture engine is exactly as described:
always-write-enabled sample BRAMs whose writes are gated by a clock-enable derived from a
free-running counter, with a small set of async-forced state flops as the re-arm path. Three
cited cells matched exactly, down to the LUT INIT mask.

The two corrections are worth passing upstream: **two of the four channels are not
LUT-gated at all** (they share one registered clock-enable), and the quoted fan-out counts
correspond to a depth-bounded trace rather than a full transitive closure.

The most useful *new* result is a set-equality proof: the write-window gating of **both**
channels and the data-ready output are driven by **one identical 358-flop control cone** —
upstream inferred this from similar cone sizes; here it is proven as exact set equality.

---

## 1. What was lifted

The stock bitstream was carved from the device application image, trimmed to its true
length (header + 722 frames × 160 B + footer = 115,638 B), and converted to an apicula
`.fs` with the project's own `bin2fs` slicing. The resulting `.fs` is **925,842 bytes**,
matching the size the upstream project reports for its stock scope image — an early
independent agreement on the input.

Decode and lift:

```
gowin_bsram_ports.py                     # BSRAM port sidecar (see §5 gap 1)
gowin_unpack.py  --device GW1N-2 --package QFN48
load.py --lifter gowin --device GW1N-2 --package QFN48
reach.py -> reach2.py -> reach3.py -> reach4.py -> auto_name.py -> patterns.py -> report.py
```

Recovered netlist:

| | |
|---|---|
| tiles configured | 317 |
| routing arcs | 37,224 |
| LUT4 | 847 |
| flip-flops / latches | 1,416 (DFF 574, DFFS 493, DFFC 148, DFFR 147, DFFP 10, DL/DLC 44) |
| ALU cells | 192 |
| IOB | 59 (25 bonded in this package) |
| BSRAM | 4 sample blocks + 6 aux |
| nets | 5,359 |
| reachability pairs | 1,926,799 |

`auto_name.py` and `patterns.py` run clean on a gowin bitstream, which the standard
pipeline currently skips for this family; they contributed little here (3 names, 2 patterns)
but did not error.

**Package note.** apicula's GW1N-2 database ships only proxy packages
(`QFN48X`/`QFN48XF`, `LQFP100`). `QFN48X` reproduces the upstream proxy pin numbers
exactly (SCLK=16, SO=17, CS_N=23, SI=24, enable=19, data-ready=32, run=35). It was used
for that reason. These are **not** the physical part's pin numbers; the IOB *location*
names are the package-independent ground truth, exactly as the upstream doc cautions.
Independently confirming that caution: `IOR1B` — the run/re-arm pad — is **unbonded in
apicula's LQFP100 entry**, so the larger proxy package silently loses the single most
important control pin.

> **Revised under issue #69.** The board package was re-derived empirically rather than
> from IOB *site* count (which proves nothing — a GW1N IOB decodes as `IBUF` from its
> default fuse state). Filtering the 59 decoded IOBs to those whose fabric side actually
> reaches a logic port leaves **23 genuinely-used pads**; the whole top edge is
> default-state IBUFs. Coverage of those 23: **LQFP100 20/23**, QFN48X 14/23, QFN48XF
> 14/23 — and the QFN48X misses include pads the design actively *drives* (e.g. the
> `IOL5B` output). `boards/fnirsi-gw1n2/board.toml` therefore stays on **LQFP100**.
> The caution above still stands for `IOR1B` specifically: it is one of 3 real pads
> LQFP100 does not bond. But apicula's tables are demonstrably incomplete proxies — 
> `IOT3A` is a routed pad unbonded in *every* GW1N-2 table — so these are most likely
> table gaps, not genuinely unbonded die pads. `load.py` now net-names every
> routed-but-unbonded pad after its location (`source='gowin_iob_unbonded'`), so
> `IOR1B` is no longer lost even without a pin number.

---

## 2. The capture datapath, as recovered

All four sample BRAMs sit in one row, at the tiles the upstream doc names, and the write
(A-port) control is uniform:

| BRAM | tile | CLKA | CEA driver | WREA | OCEA | RESETA |
|---|---|---|---|---|---|---|
| BSRAM_0 (CH1) | R10C2 | spine `GB20` | LUT `INIT=0x3300` → `~B & D` | **VCC** | **VCC** | VSS |
| BSRAM_1 | R10C5 | spine `GB40` | **FF (shared, registered)** | **VCC** | **VCC** | VSS |
| BSRAM_2 | R10C14 | spine `GB40` | **FF (shared, same net)** | **VCC** | **VCC** | VSS |
| BSRAM_3 (CH2) | R10C17 | spine `GB20` | LUT `INIT=0x0f00` → `~C & D` | **VCC** | **VCC** | VSS |

The global-spine assignments (`GB20`/`GB40`/`GB40`/`GB20`) match the upstream table
exactly. `RESETA` reaches VSS through one routing hop rather than a direct tie — the
functional claim is right, the wiring detail is one level less direct.

The write address is register-driven, as described. Of the 14 `ADA` bits, 9 are routed to
plain `DFF` outputs (a free-running counter), 2 share a single wire, and 3 are unrouted:

```
ADA4..ADA7   <- DFF (4 counter bits)
ADA9..ADA12  <- DFF (4 counter bits)
ADA2, ADA3   <- shared wire
ADA0, ADA1, ADA8, ADA13 -> unrouted
```

---

## 3. Claim-by-claim

### R3 claim 1 — "the four sample BRAMs are always write-enabled" → **CONFIRMS**

`WREA = VCC` and `OCEA = VCC` on all four blocks (direct constant ties), `RESETA = VSS`
on all four (via one hop). There is no write-enable to assert; capture is not gated by WRE.

**EXTENDS — the read port is not "unconnected".** The upstream doc flags `CLKB`/`CEB` as
unresolved placeholders. pluribus resolves the entire B side on all four blocks:

- `WREB = OCEB = RESETB = VSS` on all four — the read port structurally *cannot* write,
  which is a stronger statement than "port A is the write side".
- `CLKB` is on a global spine (`GB70` / `GB30`), not unconnected.
- `CEB` is real logic: CH1's read port is gated by a LUT with `INIT=0x3300` — the *same*
  function form as its own write gate — CH2's by `INIT=0x0c0c`, and BSRAM_1's `CEB`
  resolves to VCC through a five-hop route.

This materially changes the read-side picture: the readout is gated, not free.

### R3 claim 2 — "CEA is a combinational function of a free-running counter; CH1 `INIT=0x3300`" → **CONFIRMS for CH1, REFUTES the uniformity**

**Confirmed, exactly, for CH1.** `CEA(R10C2)` is driven by LUT `lut_r12c1_LUT3` with
`INIT=0x3300`, decoding to `~B & D`. Both of its care-inputs are register outputs — not
pins — so the "function of counter state, not of any pin" claim holds:

```
B = ff_r12c2_DFF2  (DFFP)
D = ff_r12c3_DFF2  (DFFP)
```

The upstream reading `qC & ~qB` and this `~B & D` are the same structure (one state bit
ANDed with the complement of another); the letters differ only by pin-naming convention.
The backward cone of that gate is **358 flops** (upstream: "≈383").

**Refuted: the four channels are not uniformly LUT-gated.** The upstream table lists
BSRAM_1 and BSRAM_2 as each gated by a "LUT of counter". They are not. Both `CEA` nets are
*the same net*, driven **directly by a flip-flop output** (`ff_r11c6_DFF0`, a DFFS) with no
LUT in between. Two of the four channels therefore share a single registered
capture-enable. Any model that assumes four independent per-channel window gates is wrong
for half the channels.

**Extended: the two LUT-gated channels use different bit pairs.** CH2 is `INIT=0x0f00`
(`~C & D`), not CH1's `0x3300`. They share the same `D`-term register
(`ff_r12c3_DFF2`) and differ in the inverted term (`ff_r12c2_DFF2` vs `ff_r5c16_DFF0`).
The single quoted INIT does not generalise across channels.

### R3 claim 3 — "master run/re-arm at IOR1B, driving 70 CE + 8 async-SET + 156 D" → **CONFIRMS structurally; REFUTES the counts as stated**

The pad exists and is an input buffer on die cell grid (0,19), pio B, driving fabric net
`n591`. Its sibling on the same cell (pio A) is an output buffer — matching the upstream
follow-up's observation that the run input has an output sibling.

Fan-out depends entirely on trace depth, which reconciles the numbers:

| depth | D | CE | LSR | of which async-SET (DFFS) |
|---|---|---|---|---|
| 6 | 106 | 52 | 2 | 0 |
| **8** | **187** | **68** | **32** | **8** |
| 12 | 249 | 80 | 73 | 10 |
| full closure | 534 | 116 | 114 | 12 |

The quoted `70 CE / 8 SET / 156 D` sits at **roughly depth 8** (CE 68 vs 70), **not** at
full transitive closure, where the counts are 1.7–3.4× larger. The numbers are a
depth-bounded forward trace; they should be quoted with that qualifier.

**The "8 async-SET" is exact, and its mechanism is confirmed.** At depth 8 exactly 8 DFFS
flops are reached on their async input, and **all 8 take their LSR from one net** — which
is the output of `lut_r5c15_LUT7`, `INIT=0x8000`, decoding to a true 4-input AND
`A&B&C&D`. In 1-based apicula naming that cell is **`R6C16_LUT4_7`** — precisely the gate
the upstream follow-up identifies as the re-arm AND. Independent bullseye.

**Naming caveat on "IOR1B".** apicula names this one die cell two different ways: its
package pinout calls pin 35 `IOR1B` (right-edge convention) while its own
`loc2pin_name()` calls the same grid cell `IOT20` (top-edge convention). Both refer to the
same pad. This is not an error upstream — but it is why the pad is *missing from pluribus's
pad map* (see §5 gap 2).

**Qualifies the "one master input" framing.** The same fan-out signature (CE=116, LSR=114,
identical dtype split at full closure) is produced by `IOB7B` and `IOB18B` as well as by
`IOR1B`. All three control pads converge on the same downstream cone, so "deep-drives the
capture engine" does not by itself single out `IOR1B`. This independently supports the
upstream follow-up's own correction — that arming is a *coincident* AND of run ∧ enable ∧
SPI bit rather than one master pin.

### R3 claim 4 — "captured one buffer then stopped, because run/re-arm and the SPI register aren't re-driven" → **SUPPORTED STRUCTURALLY, not independently verified**

This is a behavioural claim about a running device; a static netlist cannot confirm it.
What the netlist does confirm is every structural precondition it rests on: a level-sensitive
async force on 8 state flops from a single 4-input AND fed by the control pads, and write
windows gated by counter bits that are themselves in that AND's preset fan-out. The
mechanism is consistent; the symptom itself remains a bench observation.

### Follow-up — re-arm AND gate `R6C16_LUT4_7`, `INIT=0x8000` → **CONFIRMS (exact)**

`lut_r5c15_LUT7`, `INIT=0x8000`, `A&B&C&D`, driving the async-set net of the 8 DFFS flops.
Its four inputs are themselves gate outputs (two `INIT=0x0033`, one `0x8000`, one `0x1000`),
consistent with a coincidence detector over several control terms.

### Follow-up — SPI control-register flop `R16C9_DFFE_3` with `D ← SI` → **CONFIRMS, with a refinement**

`ff_r15c8_DFF3` (1-based `R16C9`, DFF3) exists and is **the only flop in the entire design
whose D input is within two hops of the SI pad net**. Its `D` is not raw SI: it comes
through `lut_r15c8_LUT3`, `INIT=0xa0a0` = `A & C`, i.e. **SI gated by a second signal**
before being latched.

*Not verifiable:* the flop's clock net has no modelled driver, so pluribus **cannot**
confirm the register is clocked by SCLK (see §5 gap 5).

### Follow-up — data-ready output at `IOR13A`, driven by `R12C7_DFFE_4`, cone ≈384 → **CONFIRMS, and EXTENDS significantly**

The output pad `IOR13A` (proxy pin 32) is driven by `ff_r11c6_DFF4` — 1-based
**`R12C7`, DFF4** — exactly the cited cell. Its backward cone is 358 flops (upstream 384).

**The extension is the interesting part.** That cone is not merely *similar in size* to the
CE-gate cones. It is **set-identical** to all four of them:

```
CE@R10C2  CE@R10C5  CE@R10C14  CE@R10C17  data-ready
   358       358        358        358        358   FFs
every pairwise comparison -> IDENTICAL
```

One single 358-flop control/counter cone drives the write-window gating of every channel
*and* the status output. Upstream inferred a shared cone from comparable sizes; this is a
proof of exact set equality, which a hand-trace would not cheaply produce.

### Follow-up — `IOB18A` (CS_N) unused inside the fabric → **CONFIRMS**

Its net has zero fan-out entries: wired to a pad, consumed by nothing in the fabric.

**EXTENDS:** `IOB5A` (SCLK) *also* has zero modelled fabric endpoints. It routes to local
tile wires but lands on no modelled cell. So the claim that SCLK clocks the shift register
is not reproducible here — see §5 gap 5.

### Read-side: "all four BRAMs' read data converges on SO, a 4-to-1 mux" → **NOT VERIFIABLE**

Neither confirmed nor refuted. The SO pad's drive net has no modelled driver, and **0 of 18
routed DOB bits on any of the four blocks reach it**. This is a pluribus decode gap, not
evidence against the upstream claim: because the BSRAM is not a modelled netlist cell, its
ports are not netlist pins, so nothing downstream of the memory is traceable. See §5 gap 3.

---

## 4. What pluribus surfaced beyond the hand-trace

1. **Cone set-identity** (not just size agreement) across both channels' write gating and
   the data-ready output — one shared 358-flop control cone, proven by set comparison.
2. **The read (B) port fully resolved** on all four blocks: `WREB/OCEB/RESETB = VSS`,
   `CLKB` on a global spine, and `CEB` driven by real gates — replacing "unconnected
   placeholders" with a concrete, gated read path.
3. **Two channels share one registered clock-enable** with no LUT gate — a structural
   asymmetry the uniform four-channel model misses.
4. **Per-channel CE-gate INITs differ** (`0x3300` vs `0x0f00`) while sharing one counter
   term, so the quoted mask does not generalise.
5. **Fan-out as a function of trace depth**, which reconciles the quoted counts and shows
   the same signature is shared by all three control pads — corroborating the coincident-AND
   model over a single-master-pin model.
6. **The exact async-set mechanism**: all 8 re-arm flops driven from one 4-input AND, tied
   back to the specific counter bits that feed the CE gates.
7. **Register-driven write address** confirmed bit by bit (which `ADA` bits are routed to
   counter flops and which are absorbed).

---

## 5. pluribus GOWIN decode gaps found (and precisely why)

These are engine limitations exposed by this exercise, not upstream errors.

> **Status: gaps 1 and 2 are FIXED (issue #69).** The text below is kept as the
> diagnosis of record; see the "Resolution" notes under each. Gaps 3–5 remain open.

**Gap 1 — BSRAM ports are silently dropped (the significant one).**
`gowin_unpack.py` fills hard-IP ports from the static tile database:
`db[row, col].bels[name].portmap`. For BSRAM the name is wrong. apicula's `parse_tile_()`
returns the *placed instance* name (`BSRAM0`, `BSRAM1`, …) but the static db keys the site
as plain `BSRAM`, so the lookup raises `KeyError`, the surrounding `try/except` swallows
it, and the record is emitted with **zero ports**:

```
hardip 9 1 BSRAM bel=BSRAM0        <- no CLKA/CEA/WREA/... at all
```

All 210 ports per block are lost. `ebr_ports` / `ebr_buses` stay empty for the gowin family
and the report prints "0 EBR blocks" for a design with four populated sample memories.
The ports are **not** buses — they are scalar per-bit entries — so nothing here is
intrinsically hard to model; only the name lookup is wrong. Worked around **externally** by
`scripts/gowin_bsram_ports.py`, which reads the correct site bel and resolves every port to
the same canonical node names, without touching the core lifter.

> **Resolution (#69).** `gowin_unpack.static_bel()` now normalises a placed site name to
> its static-db key by stripping a trailing index (`BSRAM0` → `BSRAM`, `BSRAM_AUX1` →
> `BSRAM_AUX`), trying the exact name first so indexed sites that genuinely exist
> (`LUT0`, `DFF3`, `ALU5`, `BANK2`) cannot be mis-bound. A real miss now calls `die()` —
> the silent degradation to an empty record is what hid this for so long. Vector and
> nested-vector portmap entries (`RAM16.RAD`) are flattened instead of skipped.
> `gowin_lift` turns the recovered ports into `ebr_ports`, `reach3` classifies them into
> `ebr_buses` (with an `addr` role: a GW1N BSRAM port has one shared address bus, not
> MachXO2's split read/write), and `report.py` prints the blocks with their nets.
> Result on this design: **4 BSRAM blocks, 840 ports, 816 with a routed net** — verified
> wire-for-wire against the bridge oracle by `scripts/gowin_bsram_verify.py`.

**Gap 2 — corner IOB physical pins do not resolve, dropping the pad from `pad_map`.**
apicula names the corner cell (0,19) `IOT20` via `loc2pin_name()` but keys it `IOR1A`/`IOR1B`
in `db.pinout`. `gowin_unpack.py` looks up the former in a table keyed by the latter, misses,
and emits `phys=-`; `load.py` then skips pads with no pin. The consequence here is pointed:
**the master run/re-arm pad is absent from `pad_map` entirely.** Its net is present and fully
analysable (`n591`), so this cross-check was unaffected once the node was identified by hand —
but `net_for_pad()` cannot find it, and any pad-driven analysis silently misses it.

> **Resolution (#69).** `gowin_unpack.iob_loc_name()` now generates both edge names for a
> corner tile and prefers whichever the package actually bonds, falling back to the L/R
> name — the convention every bonded corner in the GW1N-2 tables uses (LQFP100 names
> corner (18,19) `IOR19`; QFN48X names corner (0,19) `IOR1`). So the corner pad is
> labelled `IOR1B` regardless of package, and lands in `pad_map` with its pin number
> under any package that bonds it. Under LQFP100 — the package the evidence supports —
> apicula still has no pin for it, so it is net-named rather than dropped (see the
> package note in §1).

**Gap 3 — BSRAM is not a netlist cell.** Even with gap 1 bridged, the memory is not a cell
with pins in the graph, so no path *through* a BRAM is traceable. This is what makes the
read-side (DOB → SO) claim unverifiable.

**Gap 4 — the gowin clock spine is not unified.** `clocks.py` collapses clock domains only
for the MachXO2 `BRANCH_HPBX` track, so the global `GBxx` spine nets each surface as their
own domain: the report claims **185 "primary clocks"** for what is a handful of physical
clocks. Cosmetic here, misleading in general.

**Gap 5 — SCLK / CS_N land on no modelled cell.** Both route to local tile wires and then
to nothing the netlist models (presumably the IOLOGIC / clock path). CS_N being unused is a
genuine finding that matches upstream; SCLK is a decode gap, and it is why the SPI
register's clock source could not be confirmed.

---

## 6. Reproducing

```
# 1. BSRAM port sidecar (runs under the apicula interpreter)
python3 scripts/gowin_bsram_ports.py --device GW1N-2 --out bsram_ports.json

# 2. decode + lift + analyse (python3.15t)
python3.15t scripts/gowin_unpack.py scope.fs scope.gwconfig --device GW1N-2 --package QFN48
python3.15t load.py --label OSC2C53T --config scope.gwconfig --pins pins.tsv \
    --lifter gowin --device GW1N-2 --package QFN48 --fuzz
python3.15t reach.py --bitstream OSC2C53T      # then reach2/3/4, auto_name, patterns, report

# 3. the capture-arming trace
python3.15t scripts/gowin_capture_trace.py --bitstream OSC2C53T \
    --bsram-ports bsram_ports.json --control-node R1C20_Q6 --extra-net dataready=n2993
```

`scripts/gowin_capture_trace.py` is board-agnostic: given a control net and an optional
BSRAM sidecar it reports the same structure — BSRAM control map, CE-gate INIT decode,
depth-resolved control fan-out, async set/preset targets, and backward-cone set comparison —
for any GOWIN design.

---

## 7. Suggested corrections to pass upstream

1. **BSRAM_1 / BSRAM_2 are not LUT-gated.** They share one registered clock-enable driven
   directly by a flip-flop. The four-identical-channels table should be split 2 + 2.
2. **`INIT=0x3300` is CH1-specific.** CH2 uses `0x0f00`. Both are `one bit AND NOT another`,
   sharing one counter term.
3. **Quote the fan-out counts with their trace depth.** `70 / 8 / 156` corresponds to a
   depth-limited trace; the full closure is `116 / 12 / 534`.
4. **The read port is resolved, not unconnected** — `WREB/OCEB/RESETB = VSS`, `CLKB` on a
   global spine, `CEB` gated by real logic. Worth folding into the R1 readout plan, since it
   means the read path is itself gated.
5. **The shared control cone is exact.** Both channels' gating and the data-ready output
   share one identical 358-flop cone — stronger evidence for the single-control-cone model
   than size similarity alone.
