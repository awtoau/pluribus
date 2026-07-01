# Upstream gap analysis — MachXO2 IOLOGIC primitives

## tl;dr

- **prjtrellis**: already complete for MachXO2 IOLOGIC. No contribution needed.
- **nextpnr-machxo2**: zero IOLOGIC implementation. Needs C++ work (new cells,
  packer, bitstream writer). Our 143 Diamond bitstreams are the reference data
  and the test suite.
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

## What nextpnr-machxo2 needs (specific files)

ECP5 in the same codebase has ~600 lines of IOLOGIC packing. MachXO2 has none.
The work is porting the ECP5 pattern using our enum mappings:

| File | What to add |
|------|-------------|
| `machxo2/cells.cc` | New cell types: `IDDRXE`, `ODDRXE`, `IDDRX2E`, `ODDRX2E`, `IFS1P3*`, `OFS1P3*` — port lists + param defaults in `create_machxo2_cell()` |
| `machxo2/cells.h` | `is_iologic()` predicate |
| `machxo2/pack.cc` | New `pack_iologic()` method: find IOLOGIC cells, pair with adjacent `TRELLIS_IO` via shared `IOLDO`/`DI` nets, set `DATAMUX_ODDR`. Call from `run()` at line 1626. |
| `machxo2/bitstream.cc` | New `write_iologic()` method: write MODE + CLKIMUX + CLKOMUX + LSRMUX + GSR to the IOLOGIC tile. Dispatch branch in `run()` at line 727. |

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
