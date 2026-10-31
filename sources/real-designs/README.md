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
