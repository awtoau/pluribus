# Real-design corpus candidates (#183 blind-spot fix)

Why this exists: the entire pluribus Cyclone IV corpus (`reference/corpus_keep.tsv`, 533 designs)
was purpose-built synthetic decoder tests, zero real third-party RTL. #182/#183 showed this is a
real blind spot: a vendor-correct, corpus-clean fix (F-020, ASDATA register-feedback) still broke
a real design (the DJI image's AF3 engine, a SHA-1 compression core) because nothing in the
synthetic corpus exercised that register-feedback shape. These are real, independently-written
designs sourced to close that gap, going into the `extensive` gate tier (`scripts/cycloneiv_clean_gate.py`,
not yet backed by a design list — see `reference/gate_fast.tsv`/`corpus_keep.tsv` for the pattern
this tier should follow once populated).

Source files are gitignored (`sources/*`, same convention as the rest of `sources/` — see the
repo's own `.gitignore` and `sources/README.md`), regardless of license: even permissively
licensed third-party RTL stays out of the git tree. This file (the manifest) is tracked so anyone
can re-fetch the same set. Each entry's source URL is the re-fetch instruction.

Status column: **fetched** = file is present under `sources/real-designs/`, used or usable now.
**not fetched** = found and vetted, not yet pulled in (either lower priority, or license needs
your decision first per the project's public-repo content rules).

## Fetched, clean license, ready to use

| File | Source | License | Why it matters |
|---|---|---|---|
| `sha_v2004.v` | OpenCores `sha_core` (marsgod, 2002-2004) via VTR benchmark suite: `vtr_flow/benchmarks/verilog/sha.v`, https://github.com/verilog-to-routing/vtr-verilog-to-routing | Permissive, OpenCores-standard (quoted in file header: "may be used and distributed without restriction provided that this copyright statement is not removed... and that any derivative work contains the original copyright notice and the associated disclaimer"). No copyleft. | SHA-1 compression core — same register-to-round-feedback shape as the AF3 engine that exposed #183, but an independent implementation (different author/project), so it's a genuinely new regression specimen, not a duplicate of whatever triggered the original bug. Plain RTL, no vendor primitives, no porting needed — wrap with a Cyclone IV top-level and build. Externally validated as a "known-hard" EDA-correctness specimen: the academic FPGA-assurance project `byuccl/bfasst` independently curates this same file for toolchain verification. |
| `picorv32.v` | github.com/YosysHQ/picorv32 (archived, last substantive commit 2026-07-31, 614+ commits since 2015-06-06) | ISC (quoted from `COPYING`, verified direct: "Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear in all copies.") No copyleft. | RV32I/IM/IMC CPU core, plain Verilog-2001, zero toolchain lock-in. Pipelined control with internal hazard handling, optional PCPI multiply/divide coprocessor (`picorv32_pcpi_mul`/`_fast_mul`/`_div` — LUT-based MAC-adjacent logic, distinct shape from both DSP-block multiply and SHA-1's round feedback), optional dual-port register file (a different M9K/register-file stress pattern again). Strongest Cyclone IV field evidence of any candidate checked: the repo's own `scripts/quartus/synth_area_regular.qsf` targets `ep4ce40f29c7` with a published timing result (Cyclone IV E -7: 7.5 ns / 133 MHz); independently confirmed by `ZiCog/xoro` (MIT, DE0-Nano/EP4CE22 build) and `open-design/riscv-soc-cores` (FuseSoC, named Cyclone IV targets with exact part numbers: EP4CE22F17C6, EP4CE115F29C7, EP4CE6E22C8). |
| `vexiiriscv_minimal.v` | **Generated locally**, not fetched as a static file — different provenance from the other two rows. Source: SpinalHDL/VexiiRiscv submodule checkout at `/mnt/2tb/git/cynthion-workspace/repos/vexiiriscv` (Dan's Cynthion bring-up workspace), updated to `origin/dev` tip commit `03345d8d013a961d6c3ae8474f4f73e5a5523ccc` (2026-10-31), generated via `sbt --batch "runMain vexiiriscv.Generate --xlen 32"` run from the repo root with its `ext/SpinalHDL`/`ext/NaxSoftware`/`ext/riscv-isa-sim`/`ext/rvls` submodules aligned to that commit's recorded pointers (a prior mismatch there breaks the sbt compile — see `linux-on-cynthion/BRINGUP_PLAN.md`'s own issues table for the same class of failure). Re-generate with the same command from a matching checkout. | MIT (quoted from `LICENSE`, copyright SpinalHDL): "Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the Software), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software... The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software." No copyleft. | SpinalHDL's current/primary RISC-V core (VexRiscv's successor), proven on real ECP5 hardware via Dan's own Cynthion (LFE5U-12F) bring-up work. Config used is `ParamSimple`'s bare default plus `--xlen 32` only — no `--with-rvm`/`--with-rvc`/cache/BTB/supervisor flags — confirmed by the generator's own log line `ISA extensions: i, zicsr, zifencei`: plain RV32I + Zicsr + Zifencei, single hart, machine-mode only (`PrivilegedParam.base`, no supervisor, no MMU), matching what Cynthion's shipped `cynthion+jtag` VexRiscv-class firmware actually runs bare-metal. Structurally new blind-spot shape vs. the other two rows: cacheless `FetchCachelessPlugin`/`LsuCachelessPlugin` buses (Spinal's own valid/ready stream handshake, not Wishbone/AXI/Avalon — a third bus-protocol shape in this corpus), a single `ExecuteLanePlugin` (single-issue, not dual-issue) fed by separately-staged `FetchPipeline`/`DecodePipeline` plugin chains (VexiiRiscv's composable-plugin pipeline, architecturally distinct from PicoRV32's monolithic FSM-pipeline and from SHA-1's round-register feedback), and a 2-read/1-write-port `RegFileMem` built from discrete always-block logic rather than a single inferred multi-port array. Fully self-contained: 3 modules total (`VexiiRiscv`, `RegFileMem`, `StreamArbiter`), no blackboxes, no `$display`/DPI/non-synthesizable constructs — verified plain portable RTL, no SpinalHDL runtime dependency at synthesis time. **Not yet added to git** — like the other rows, `sources/real-designs/*` is gitignored regardless of license; the file sits at `sources/real-designs/vexiiriscv_minimal.v` locally and this manifest row is the re-fetch (here, re-generate) instruction. |

## Vetted, not fetched — needs a policy decision (generated/converted RTL, not hand-written)

Both clear the license bar (permissive) but don't match the "plain hand-written RTL, no generation
step" bar `sha_v2004.v`/`picorv32.v` were held to — worth a decision on whether a generated-and-
vendored `.v`/converted-from-VHDL file is acceptable before either goes in.

| Project | URL | License | Why it's wanted | Why it's not fetched yet |
|---|---|---|---|---|
| `litex-hub/pythondata-cpu-vexriscv` | https://github.com/litex-hub/pythondata-cpu-vexriscv | MIT | Pre-generated plain-Verilog VexRiscv builds (`VexRiscv.v`, `VexRiscv_IMAC.v` with hardware M-extension, `VexRiscv_Linux.v`), checked into git — deepest pipeline/hazard-forwarding and genuine multi-port regfile of any candidate found. VexRiscv's own README states a real Cyclone IV result (143 MHz, 2,076 LUT, 972 FF); `myriadrf/LimeSDR_GW` (Apache-2.0, a real shipped SDR product) uses it on Cyclone IV EP4CE40. | Generated from SpinalHDL/Scala source, not hand-written — the vendored `.v` is usable without the Scala toolchain, but *regenerating/reconfiguring* it needs one. |
| NEORV32 (`stnolting/neorv32`) | https://github.com/stnolting/neorv32 | BSD-3-Clause | Full MCU-class SoC (MMU, PMP, debug module, caches, crypto ALU). Real Cyclone IV deployment confirmed multiple ways, incl. `emb4fun/wb_tiny_emac`'s README: "hardware-proven (DE2-115 / Cyclone IV, NEORV32 at 90 MHz, lwIP driver)". | VHDL-native; a Verilog netlist needs a GHDL conversion step (`stnolting/neorv32-verilog`, now folded into the main repo) — not a checked-in `.v`. Also confirm pluribus's own pipeline ingests VHDL at all before relying on this. |

## Vetted, not yet fetched — license needs your OK first

These are real, found-in-the-wild designs that directly hit coverage gaps (M9K true-dual-port mode,
register-heavy FSM logic) but carry copyleft or undeclared licenses. Per this project's content
rules, pulling and using copyleft-licensed RTL into pluribus's own corpus/test flow needs an
explicit decision, not an agent's judgment call. Each is a straight `git clone`/fetch away if
cleared.

| Project | URL | License | Why it's wanted |
|---|---|---|---|
| `ThroatyMumbo/NESPC` | https://github.com/ThroatyMumbo/NESPC | GPL-3.0 | `rtl/fb.sv` explicitly instantiates `altsyncram` with `.intended_device_family("Cyclone IV E")` in **true dual-port** mode — direct hit on the M9K TDP-beyond-x16/18 gap (`docs/altera/cycloneIV/cycloneiv-clean-gap-audit.md` §5), plus FSM-heavy 6502-class CPU logic. |
| `douggilliland/MultiComp` (Cyclone IV VGA Card sub-project) | https://github.com/douggilliland/MultiComp | none declared | Multiple retrocomputer (6502/6800/Z80/68000) builds; in-tree Quartus `.map.rpt`/`.merge.rpt` files already confirm **True Dual Port** altsyncram instantiations (`DisplayRam2K`, `vram_8k`) fitted for real Cyclone IV builds — independent confirmation of TDP usage in the field, not just inferred from source. |
| `zhong1212/sha256-fpga-de2-115` | https://github.com/zhong1212/sha256-fpga-de2-115 | none declared | SHA-256 core + UDP network stack, explicitly built for DE2-115 (Cyclone IV E). Same register-feedback shape class as `sha_v2004.v` but SHA-256 (64-round) rather than SHA-1 — a second, larger specimen in the same blind-spot family. |
| VTR benchmark `or1200.v` | `vtr_flow/benchmarks/verilog/or1200.v`, same VTR repo as `sha_v2004.v` | LGPL-2.1 (OpenCores header, confirmed by reading the file) | OpenRISC 1200 CPU core — real register/pipeline-heavy CPU, 135KB of RTL. |

## Noted, lower priority (second wave if the above proves insufficient)

- **VTR Koios 2.0 benchmarks** (`vtr_flow/benchmarks/verilog/koios/`, 40 designs — `gemm_layer.v`, `conv_layer.v`, `tpu_like.*.v`, `lstm.v`, etc.) — VTR's own MIT license (confirmed, these are VTR-authored not third-party-sourced like `sha.v`). Good DSP/MAC and BRAM-inference coverage in varied modes (`` `define complex_dsp ``/`` `define hard_mem `` switches select hard-primitive vs. plain-behavioral fallback — the plain-behavioral mode is what would synthesize for Cyclone IV without VTR's own 22nm architecture lock-in). Bigger, more complex designs (deep-learning-accelerator proxies) — recommend only after `sha_v2004.v` is proven in.
- `bge007/ep4ce6e22-enc28j60-ethernet` (license not fully verified) — ARP/ICMP/UDP stack, explicit EP4CE6E22 target, FSM-heavy protocol parsing — different blind-spot class (control-flow FSMs, not register feedback).
- `emb4fun/wb_tiny_emac` (license not fully verified; VHDL, not Verilog — confirm pluribus VHDL support before counting on this) — Ethernet MAC, "hardware-proven on FPGA (Cyclone IV, NEORV32)".
- ISCAS89/ITC99/MCNC academic benchmark RTL ports exist (`ccsl-uaegean/ITC99-RTL-Verilog` — GPL-3.0; `bluesceada/iscas89_hl_verilog`, `jpsety/verilog_benchmark_circuits` — no license declared) — none already built for Cyclone IV by anyone, and mostly combinational/small-sequential shapes, lower relevance to the register-feedback blind spot even disregarding license. Not recommended unless a specific new gap needs them.

## Ruled out

- yosys's own test suite (`tests/memories/`, `tests/fsm/`, `tests/bram/`) — checked directly, all tiny synthetic unit tests (largest non-generated file ~13KB), same blind-spot category as our own corpus. Not corpus-worthy.
- SymbiFlow/F4PGA — Apache-2.0 but targets Xilinx/Lattice only, zero Altera/Cyclone IV designs found.
- Icarus Verilog / Verilator regression tests — target simulation-semantics edge cases (multi-driver nets, delay races), a different axis from the synthesis/placement-shape blind spot here.

## Re-fetch

```
mkdir -p sources/real-designs
curl -s -o sources/real-designs/sha_v2004.v \
  https://raw.githubusercontent.com/verilog-to-routing/vtr-verilog-to-routing/master/vtr_flow/benchmarks/verilog/sha.v
```

`vexiiriscv_minimal.v` is generated, not fetched. From a checkout of
`SpinalHDL/VexiiRiscv` with submodules aligned (`git submodule update --init
--recursive`):

```
sbt --batch "runMain vexiiriscv.Generate --xlen 32"
cp VexiiRiscv.v sources/real-designs/vexiiriscv_minimal.v
```
