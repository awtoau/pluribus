# Upstream contributions — MachXO2 open-source toolchain

Tracking issue: https://github.com/awtoau/pluribus/issues/19

This document is the canonical record of all upstream work stemming from
Pluribus's diamond-fuzz RE. It covers what we have, what each project needs,
and the current status of each contribution.

Patches and check.py files live in `upstream_patches/` in this repo.

---

## tl;dr

- **prjtrellis**: already complete for MachXO2 IOLOGIC bitfield data. We have
  a check suite + two patches ready to PR. No new fuzzing needed.
- **nextpnr-machxo2**: **DONE (local fork, commit c1f89eb).** IDDRX1F/ODDRX1F
  packing and bitstream generation implemented across 6 files, 217 lines.
  Fuzz confirms 100% wire globalise on all 158 iologic runs (previously 0/158).
  Ready to upstream as a PR.
- **prjcombine**: IOLOGIC bels are wiring stubs only. Blocked on upstream
  geometry model completion. Longer term.
- **Diamond EULA**: not a problem. prjtrellis explicitly uses Diamond as a
  black-box oracle — same as Project X-Ray does with Vivado. Accepted practice.
- **nextpnr-machxo2**: **IMPLEMENTED** — IDDRX1F/ODDRX1F support added in
  local fork at `/mnt/2tb/git/nextpnr/`, commit c1f89eb. See implementation
  notes below.
- **prjcombine**: IOLOGIC bels are wiring stubs only. No DDR primitives defined
  for MachXO2 *or* ECP5. Requires finishing the MachXO2 geometry model in Rust
  before IOLOGIC primitives can be added. Longer-term than nextpnr.
- **Diamond EULA**: not a problem. prjtrellis explicitly uses Diamond as a
  black-box oracle ("Diamond is asked to generate designs, bitstreams are
  cross-correlated") — same as Project X-Ray does with Vivado. Accepted practice.

---

## Tool map

| Tool | What it does | MachXO2 IOLOGIC state |
|------|--------------|-----------------------|
| **Diamond** | Lattice closed-source synthesis + PAR + bitgen | Complete — the oracle |
| **prjtrellis** | Tile-level bitstream database (bit positions → enum names) | **Complete** — all IOLOGIC enums characterised by fuzzers 060–067 |
| **Yosys** | Verilog → gate netlist synthesis | Complete — passes `IDDRXE` etc. through as black-box cells |
| **nextpnr-machxo2** | Place & route → bitstream | **Zero IOLOGIC**. No cell types, no packer, no bitstream writer. |
| **prjcombine** | Device geometry model (separate project, single dev) | **Stub only** — IOLOGIC tile wiring mapped, no DDR primitive bels defined |
| **Pluribus** | Generic MachXO2 netlist analyser (our tool) | Full — loads any `.config`, traces reachability, exports Verilog |

---

## Why prjtrellis is already complete

prjtrellis fuzzers use NCL (Diamond's internal netlist format) to program tile
configs directly — `cellmodel-name IOLOGIC; program "MODE:IDDR_ODDR"` — bypassing
Verilog synthesis. This lets them sweep every enum value independently.

Our `iddrxe_bank0.config` confirms: `IDDRXE` synthesises to exactly the enums
fuzzers 060–061 already cover:

```
enum: IOLOGICB.MODE IDDR_ODDR
enum: IOLOGICB.CLKIMUX INV
enum: IOLOGICB.CLKOMUX INV
enum: IOLOGICB.GSR DISABLED
enum: IOLOGICB.LSROMUX LSRMUX
```

All already in `bits.db`. The bit positions are known. The gap is not here.

---

## Why the gap exists

The root cause is Diamond dependency. To fuzz MachXO2 IOLOGIC *at the Verilog
primitive level* you need Diamond — it's the only tool that can synthesise
`IDDRXE` to a routed bitstream. Diamond is:
- Closed-source, node-locked licence tied to a MAC address
- ~2GB install, fragile batch TCL interface
- Not available in CI

Most open-source contributors don't have it. Nobody with Diamond has had the
motivation to close the gap. We are the exception: Diamond installed, licensed,
143 primitives already synthesised cleanly.

---

## nextpnr-machxo2 IOLOGIC implementation (DONE)

Implemented in `/mnt/2tb/git/nextpnr/`, commit `c1f89eb`. 217 lines across 6 files:

| File | What was added |
|------|----------------|
| `machxo2/constids.inc` | `TRELLIS_IOLOGIC`, `IDDRX1F`, `ODDRX1F`, `SCLK`, `CLKIMUX`, `CLKOMUX`, `LSRIMUX`, `LSROMUX` |
| `machxo2/cells.cc` | `TRELLIS_IOLOGIC` branch with all 13 BEL pins (CLK, LSR, CE, PADDI, OPOS, ONEG, TS, DI in; IOLDO, IOLTO, INDD, IN, IP out) |
| `machxo2/pack.cc` | `pack_iologic()` pass: maps IDDRX1F/ODDRX1F → TRELLIS_IOLOGIC, finds paired \*IOLOGIC BEL via `getBelsByTile()`, handles all BEL variants (IOLOGIC/TIOLOGIC/TSIOLOGIC/RIOLOGIC/BIOLOGIC/BSIOLOGIC) |
| `machxo2/arch.h` | `isValidBelForCellType()` override: TRELLIS_IOLOGIC valid on any \*IOLOGIC-family BEL |
| `machxo2/arch.cc` | `TMG_IGNORE` timing class for TRELLIS_IOLOGIC |
| `machxo2/bitstream.cc` | `write_iologic()`: emits `MODE=IDDR_ODDR`, `GSR`, `SRMODE`, `CLKIMUX`, `CLKOMUX`, `LSRIMUX`/`LSROMUX`, `DATAMUX_ODDR` to PIC tile |

### Key implementation decisions
- BEL name derivation: iterate `getBelsByTile(x, y)` for matching \*IOLOGIC BEL with same slot letter as PIO — handles TSIOLOGICC ≠ IOLOGICC pattern at top-row tiles
- `iol.back()` for slot extraction in bitstream.cc, not `substr(7)` (would break for TSIOLOGICC, TIOLOGICC, RIOLOGICC)
- CLKIMUX/CLKOMUX default = "CLK" (nextpnr uses non-inverted clock unlike the Diamond-synthesized IDDRXE/ODDRXE which uses "INV")

### Test results
- IDDRX1F: routes on LCMXO2-1200HC-4SG32C, correct `TSIOLOGICC.MODE IDDR_ODDR` config
- ODDRX1F: routes correctly, `PIOC.DATAMUX_ODDR IOLDO` set
- Fuzz: all 158 iologic runs pass (100% wire globalise), up from 0/158

### To upstream
- PR target: https://github.com/YosysHQ/nextpnr
- Need: test designs verified against Diamond bitstreams (CLK mux setting may differ)

---

## What prjcombine needs (longer term)

`re/lattice/rd2geom/src/io/machxo2.rs` (824 lines) wires the IOLOGIC routing
fabric correctly but has no DDR primitive bels — `IDDRXE`, `IFS1P3*` etc. are
absent. A `process_iologic_machxo2()` function is needed to register these bels
with their fabric-facing pins (`Q0`, `Q1`, `D`, `CLK`, `CE`, `LSR`).

ECP5 is in a similar state — ECP5 IOLOGIC in prjcombine is also wiring-only.
This is a deeper Rust contribution and is **not blocked on us** — it's blocked
on prjcombine's author finishing the MachXO2 geometry model.

---

## Our data as a test suite

Every one of our 143 Diamond `.config` files is a ground-truth test case:

1. Take `fuzz.v` for a primitive (already exists in `diamond-fuzz/targets/`)
2. Run through nextpnr-machxo2 (after our fix)
3. Unpack both bitstreams with ecpunpack → `.config`
4. Diff IOLOGIC tile enums — must match Diamond exactly

`parse_results.py` already does this diff. The test harness is essentially
already written. This makes our PR verifiable: "here are 143 designs, here is
the automated check, it passes."

---

## Primitive → enum mapping (from our .config files)

| Verilog primitive | MODE | CLKIMUX | CLKOMUX | GSR | LSROMUX | Notes |
|-------------------|------|---------|---------|-----|---------|-------|
| `IDDRXE` | `IDDR_ODDR` | `INV` | `INV` | `DISABLED` | `LSRMUX` | Basic DDR input |
| `ODDRXE` | `IDDR_ODDR` | `INV` | `INV` | `DISABLED` | `LSRMUX` | Basic DDR output |
| `IDDRX2E` | `IDDR_ODDR` | `INV` | `INV` | `DISABLED` | `LSRMUX` | + ECLK routing |
| `ODDRX2E` | `IDDR_ODDR` | `INV` | `INV` | `DISABLED` | `LSRMUX` | + ECLK routing |
| `IFS1P3BX/DX/IX/JX` | `IREG_OREG` | `CLK` | `CLK` | varies | `LSRMUX` | Input register |
| `OFS1P3BX/DX/IX/JX` | `IREG_OREG` | `CLK` | `CLK` | varies | `LSRMUX` | Output register |

(Full mapping extractable from `diamond-fuzz/results/*/` `.config` files)
