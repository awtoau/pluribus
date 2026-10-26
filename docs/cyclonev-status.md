# Cyclone V (e50f / 5CEBA4U19C8): parked status

Parked 2026-10-24 until we know whether a Cyclone V part is needed. Everything below is on `main`.

## Where it is
- **Corpus:** 256 designs, 256 Quartus-built, `corpus/cyclonev/<design>/`.
  - Tracked: `src/` and `design.toml`.
  - Gitignored: build outputs, `bitstream.rbf`, `bitstream.compressed.rbf`, `postfit.vo`, `rcf`, `decomp.bt`, `corpus.db`.
  - Builder: `scripts/cyclonev_corpus_build.py`. Generator: `scripts/cyclonev_construct_gen.py`. Report: `scripts/cyclonev_construct_report.py`.
- **Decoder (native, default):** `scripts/cyclonev_decode.py` (`.rbf` -> `.bt`, and `encode_rbf` back). Tables in `scripts/cyclonev_native_tables.py`, corrections in `scripts/cyclonev_native_overrides.py`. Doc: `docs/cyclonev-native-decoder.md`.
- **Compressed streams:** `scripts/cyclonev_decompress.py`, validated 236/236 against Quartus. Doc: `docs/cyclonev-compressed-rbf.md`.
- **Unpack:** `scripts/cyclonev_unpack.py` (`--decoder native|mistral`, `--crosscheck`). Mistral is cross-check only.
- **Lifter:** `lifters/cyclonev_lift.py`. Sibling of ECP5 and MachXO2; no shared flags.
- **Oracles:**
  - post-fit netlist: `scripts/cyclonev_vo_parse.py`, `scripts/cyclonev_postfit_compare.py`
  - routing (RCF): `scripts/cyclonev_rcf_parse.py`, `scripts/cyclonev_rcf_crosscheck.py`
  - clock tree: `scripts/cyclonev_clock_tree_extract.py` (data in `lifters/data/cyclonev_e50f_clocks.json`)
  - docs: `docs/cyclonev-postfit-oracle.md`, `docs/cyclonev-rcf-oracle.md`
- **Scorecard:** `scripts/cyclonev_lift_scorecard.py`.

## Status (measured 2026-10-26)
- **Functional gate** (`scripts/cyclonev_lifted_sim_check.py --all`; lifted Verilog simulated, per output sample matched / wrong / missing):
  - iverilog (default): 256 designs, 256 PASS. Samples: matched 6437030 / 6437030; wrong 0, missing 0. PLL designs run on Questa (encrypted atoms).
  - Questa (`--sim questa`, `build.vo` on the vendor libraries only, incl. encrypted DSP / PLL atoms): 256 PASS, 0 FAIL. Samples matched 6437032 / 6437032, wrong 0, missing 0.
  - Reference per kind (iverilog): logic, carry, registers, M10K, MLAB: Quartus `build.vo` on the vendor models (RAM/MLAB: plain `cyclonev_atoms.v` + `altera_lnsim.sv`). DSP: `build.vo` on our model, plus lifted vs the design's own RTL. PLL: vendor atoms (Questa) vs our FPLL model.

| kind | designs | PASS | FAIL | matched / samples | wrong | missing |
|---|---|---|---|---|---|---|
| combinational | 93 | 93 | 0 | 996462 / 996462 | 0 | 0 |
| carry | 18 | 18 | 0 | 373674 / 373674 | 0 | 0 |
| registered | 87 | 87 | 0 | 1928225 / 1928225 | 0 | 0 |
| registered + carry | 15 | 15 | 0 | 512125 / 512125 | 0 | 0 |
| M10K | 24 | 24 | 0 | 771892 / 771892 | 0 | 0 |
| MLAB | 5 | 5 | 0 | 132825 / 132825 | 0 | 0 |
| DSP | 11 | 11 | 0 | 1416611 / 1416611 | 0 | 0 |
| PLL | 3 | 3 | 0 | 305216 / 305216 | 0 | 0 |

  - Before this work (start of session): 165 pass, 47 fail (registers), 24 not covered (RAM 22, DSP 2); matched 3441733 / 3804461 (90.5%).
  - Register controls (enable, async clear, sync clear, negedge): emitted from the lifter's `ctl`; the 47 failures are gone.
  - RAM: 18 M10K + 4 MLAB designs from before and 7 added (init contents, ROM, single port, dual clock) pass. Contents, widths, clocks, modes are decoded from the bitstream. `c_rom_vnd_mlab_8` was placed in an M10K by Quartus (counted under M10K).
  - DSP: own `cyclonev_mac` model (vendor atom is encrypted), validated: `build.vo` on it vs source RTL, 11 / 11 designs (`scripts/cyclonev_dsp_model_check.py`). Lifted vs source RTL 1416611 / 1416611.
  - DSP model vs the encrypted vendor atom (`scripts/cyclonev_dsp_vendor_check.py`, Questa): 267 / 267 configs, 51264000 / 51264000 bits after fixing `m9x9` bits above 17 (#121).
  - PLL: netlist lifted (refclk pad, reset, lock, output counter -> clock net) on our model `lifters/data/cyclonev_fpll_model.v`, measured against the vendor atoms; 3 / 3 PASS, decode 4 / 4 counters. Refclk pad table: 13 / 13 FPLL pin-site combinations evidenced (`CLKIN_0_SRC` = 4 + index in the FPLL `clkin` pad list; 12 `c_pllpin_*` designs + the H10 ones, all PASS on Questa). Detail: `docs/cyclonev-postfit-oracle.md` "PLL".
  - Model check (Quartus netlist + models vs `src/`): `model=ok` on every simulated design with a comparable sample, 0 wrong.
- **Structural (lifter fields vs Quartus post-fit, `scripts/cyclonev_lift_scorecard.py`), matched / total:**
  - The compare applies Quartus's `!` flags, so LUT masks and output buffers are scored as functions of
    the nets (before this, the scorecard read 100% while lifted.v was functionally wrong).
  - LUT function 3288 / 3288 (236 constant-0 cells excluded with a stated rule); LUT inputs 11093 / 11093
  - arithmetic function 741 / 741; carry and share 431 / 431
  - flip-flop control sources 2794 / 2794 each (present, D, clock, edge, domain, clear, enable, sync-clear, load).
  - pins 4556 / 4556; output buffers 1556 / 1556. Extra and wrong are 0 in every field.
- **Native decoder:**
  - CRAM frames: 1,170,088, all CRC-16 valid.
  - Routing pips: 39,550 / 39,550 against RCF. About half of RCF edges have no native node and are unscored.
  - LUT masks: 98.5%. Flip-flop presence: 98.5%. Pin use and direction: 97.6%.
  - Held-out split (family-level): routing 100% on both halves.
- **Verification:** `scripts/cyclonev_verify_all.py --skip-die-probe --skip-dsp-fuzz`: all stages PASS (stage 5 iverilog gate, stage 6 Questa gate + DSP vendor check, selftest, pad map). Stage 5/6 no longer deadlock on `tmp/heavy.lock` (nested flock). Selftest `regbank16` baseline is 140 nets: 61 LUT outputs + 64 FF Q + 15 input pads, checked against the Quartus post-fit `.vo` (its 141 includes `clkena.outclk`, the clock pad net in the lift); 139 was never produced by any lifter commit (#121).
- **Tests:** `python3 -m pytest tests -q` passes (217).
- **Gate notes:** self-feeding LUTs (Cyclone V) are emitted as `reg _fb_<z> = 1'b0; always @* _fb_<z> = lut[..{_fb_<z>}..]`: the vendor `cyclonev_lcell_comb` has `combout_tmp = 0` at t=0, so a hold latch powers up at 0, not X (Questa 0 missing on `c_latch_v95_1`). A zero-delay inverting self-loop (`c_latch_v95_1` q3) has no reference in Quartus either; the gate holds its enable input at 0. Step limits: stall (no CPU progress 60 s) + 3x measured backstop (#121).

## Still open
1. ~~`_lut_self_latch()`~~ closed 2026-10-24: removed. `c_latch_v95_1` (Quartus-built) showed it wrong (q1 never sets, q2 refused, oscillator emitted as a latch). Detail: `docs/cyclonev-postfit-oracle.md` "Self-feeding LUT latch".
   - Item 9 below (port-space masks, pad inverters): closed.
2. **Memory LABs (MLAB):** RAM halves are lifted (gate passes). Still open: in the four `c_ram_vnd_mlab_*` designs 8 CRAM bits are unclaimed and 224 frames fail their EDCRC.
3. **Clock tree:** validated on two corpus pads (K17, L17) only. PLL inputs, HR/VR muxes and other clock paths have no evidence.
4. **Tables without an oracle:** PLL, HMC, I/O standards and M10K widths still come from Mistral's data.
5. **Flip-flop controls and option RAM:**
   - Closed 2026-10-24: `sclr` 2794/2794 and `sload` 2794/2794 (the "93-97%" figure was stale); feedback-only flip-flops are recovered (`ff.present` 2794/2794, extra 0; rule: `uses_fb and FEEDBACK_SEL == slot` in `lifters/cyclonev_lift.py`).
   - `sload` as a signal stays unclaimed: all 2794 Quartus registers tie `sload` to gnd (1344) or vcc (1450). The lifter's const rule (1 iff pin-fed) is the only rule the corpus supports.
   - Not closed: CRAM option bit 6.3 and the CvP bit. `OPT_B` is `ffffff40.2dffffff` in all 237 designs, so the corpus cannot name either bit; naming needs a knob build.
6. **Re-encode check:** first step done 2026-10-26 (`scripts/cyclonev_reencode.py`, #112), see "Re-encode round trip" below. A one-LUT-bit Verilog-change rebuild is still not done.
7. **Dies:** e50f (die byte 0x05) and, since 2026-10-26, the gt150f die = 5CEBA7 / 5CEFA7 (die byte 0x13), see "Second die" below. sx50f, sx120f and any HPS die are refused.
9. ~~**lifted.v polarity**~~ closed 2026-10-24: LUT tables are over the nets, pad output inverters are NOT rows (rule: `docs/cyclonev-postfit-oracle.md` "Polarity"). Gate: `scripts/cyclonev_lifted_sim_check.py --all`, stage 5 of `cyclonev_verify_all.py`.
10. ~~**Register controls in lifted.v**~~ closed 2026-10-24: emitted from `ffs.d/clk/ce/lsr` + `ffs.dtype` flags (no schema change). Gate: registered 87 / 87.
11. ~~**Sim gate not covered (RAM, DSP)**~~ closed 2026-10-24: RAM on the plain vendor models, DSP on our own model. Remaining gaps:
    - **PLL:** closed 2026-10-26 (3 / 3 PASS on Questa). Refclk pad closed 2026-10-26 (see PLL). Open: `CLKIN_0_SRC` = 0 (core / PLL-cascade refclk from the clock network) is detected, not lifted; phase shift, presets, bypass, fractional mode, cascade, switchover are NOT LIFTED.
    - **DSP:** only independent multiplies and sum-of-2 (`m9x9` lane 0, `m18x18_full`, `m27x27`, `M18X19_COMBINED`) are decoded and modelled; accumulate, pre-adder, coefficients, chainout, scan chains, `aclr`, `m9x9` lanes 1-2 give X in the model and are not lifted.
    - **Cross-check:** Questa-Altera Starter installed (`scripts/questa.py`); `--sim questa` and `scripts/cyclonev_dsp_vendor_check.py`, stage 6 of `cyclonev_verify_all.py`.
    - **RAM:** `bidir_dual_port`, widths other than x20 / x40, init outside those layouts, byte enables, ECC: no corpus evidence; the lifter reports the block as `NOT LIFTED` with the reason.
8. **Not scored field by field:** I/O drive, slew and standard (no variation in the corpus). RAM, MLAB and DSP parameters are checked by simulation only.

## Re-encode round trip (#112 step 1, measured 2026-10-26)
- Flow: native-decode the original `.rbf` -> lift -> emit `cyclonev_lcell_comb` / `dffeas` from the lifted rows only (masks rebuilt through the LAB-pin <-> port map; adder halves solved into f0 / f2) -> QSF `PIN_*` / `LABCELL_*` / `FF_*` from the lifted ALM place -> map, fit, asm, cpf -> native-decode the new `.rbf` -> `.bt` line diff.
- Headline = matched / (matched + missing + extra + wrong), per decoded `.bt` line (settings, routes, inverters, options):

| design | stage | matched / total | missing | extra | wrong | raw `.rbf` XOR bits |
|---|---|---|---|---|---|---|
| c_cmp_eq_v95_4 (combinational) | A free routing | 89 / 102 (87.3%) | 6 | 6 | 1 | 112 |
| c_shiftreg_v95_4 (registered) | A | 118 / 131 (90.1%) | 6 | 6 | 1 | 98 |
| c_adder_v95_4 (carry) | A | 152 / 166 (91.6%) | 6 | 6 | 2 | 298 |
| same three | B original RCF imported (oracle) | identical to A | | | | identical to A |

- Fault list by category (every count above is one of these):
  - Constant-GND helper cell (`~QUARTUS_CREATED_GND~I`): 6 missing + 6 extra per design (`TSCLR_DIS`, `TPKREG0/1`, `BSCLR_DIS`, `BPKREG0/1` of one ALM). The lifter drops constant-0 cells, so the lifted netlist has no such cell; Quartus creates its own and puts it in a different tile (original LAB.019.035 / MLAB.045.003 / MLAB.004.001, regenerated LAB.012.003).
  - `o JTAG_ID`: 1 wrong per design, a checksum-like value that changes with any content difference (counted, not a netlist fault).
  - LUT mask: 1 wrong (c_adder, `LAB.001.019:LUT_MASK.5` low word `0f0fcccc` vs `3f3ffcfc`): the lifted sum / cout tables fix `f0 ^ in2` and `f0 & in2` but not which of f0 / in2 owns a bit when both depend on the same port; 19 ambiguous bits, the solver picks one split.
  - Routing (`r` lines), pad settings (`GPIO`), inverters, `DQS16`, clock-mux settings: 0 missing, 0 extra, 0 wrong in the final runs. Fit with the same placement and netlist reproduces the original routes without help.
- Stage B (RCF import) is accepted (fit msgs 170118, 170239: 80.77% of routes preserved on c_adder, 0 `Cannot route`) and gives the same result as stage A. The RCF there is the original build's, not one generated from lifted data: lifted routes cannot be written as an RCF yet, because about half of the RCF edges have no native node (IO_* path, LAB_INPUT, clock buffers; see the native decoder doc). That is the next category to close.
- Found while building it: lifting a **native-default** `.bt` loses the clock pad net (`K17 net_in = None`, 0 clock links) where the Mistral `.bt` and native `--mistral-compat` keep it. The default mode emits the SCLK/DCMUX link lines libmistral skips; the lifter's clock-tree resolution does not handle them. `cyclonev_reencode.py` lifts from compat mode.
- Not covered: registers with clear / sync-clear / load, MLAB, RAM, DSP, PLL, designs with non-default `!` port polarity, and unclaimed bits (the diff sees decoded lines only; ~1.5% of set bits are unclaimed).
- Cost: map 4 s + fit 7 s + asm 2 s + cpf 0.3 s per design (2026-10-26); the 3-design run is about 40 s once the heavy lock is free. Command: `python3.15t scripts/cyclonev_reencode.py c_cmp_eq_v95_4 c_shiftreg_v95_4 c_adder_v95_4 [--rcf]`.

## Die probe and DSP fuzz (run 2026-10-26)
- `cyclonev_verify_all.py --compile-workers 2`, stages 1-2: die probe 7 / 7 dies compiled (68.3 s), DSP fuzz 4 / 4 modes confirmed, 0 mismatch / missing (31.2 s). OVERALL PASS; nothing needed fixing.
- Both are in the default full run (flags only skip them); default `--compile-workers` is now 2.

## Vendor database (.ddb), 2026-10-26
- Container fully decoded (all 2,708 files; format `docs/cyclonev-ddb-format.md`): `scripts/cyclonev_ddb_decode.py`, tests `tests/test_cyclonev_ddb.py`.
- Die map from `device.db` + hdr: 0x05 = `cyclonev_e50f` (5CEBA4/5CEFA4), 0x13 = `cyclonev_d6_gtf150` (5CEBA7/5CEFA7, 56,480 ALM). Die byte = option-RAM strip 6 bits 19..26 (`cyclonev_decode.die_byte`).
- `asm.ddb` decoded to records of (source node -> destination-mux select bits): `scripts/cyclonev_ddb_asm.py`. Routing CRAM position set identical to the native tables on both dies (6,072,456 and 17,012,500 positions, 0 extra, 0 missing).
- (mux, code) pairs vs native: e50f 11,764,244 matched, 1,794,432 missing, 597,698 extra (all-bits-set code), 0 wrong = 83.1 %; gt150f 33,061,705 / 5,091,215 / 1,679,292 / 0 = 83.0 %. Missing ~98 % = sources in the die-edge tile ring. Detail in the format doc.
- Not done: routing graph / icname -> node names, so the native tables are still Mistral-sourced; the vendor file independently confirms the routing bit positions and codes, not source identities. Block-mux (LUT, FF, IO) bits are not in asm.

## Second die: 5CEBA7 / gt150f (die byte 0x13)
- Tables: Mistral-sourced like e50f (`cyclonev_native_tables.py 5CEBA7U19C8`; CRAM 7605 x 7024, 90 x 82 tiles, 1,934,054 muxes, 4,310 LAB + 1,338 MLAB + 686 M10K + 156 DSP).
- `cyclonev_decode.py` / `cyclonev_unpack.py --device auto` pick the die from the die byte; strict decode refuses a model/die-byte mismatch.
- Corpus `corpus/cyclonev_e150/` (18 designs, Quartus Lite 25.1 builds 5CEBA7U19C8, src tracked, outputs gitignored; `PLURIBUS_CV_CORPUS=cyclonev_e150 PLURIBUS_CV_DEVICE=5CEBA7U19C8 python3.15t scripts/cyclonev_corpus_build.py`). All 18 build, decode (all container CRCs valid), lift.
- Native vs mistral-cv `.bt`: identical in compat mode (adder12 checked); default mode differs only in the classes known from e50f (GCLK/CMUX -> SCLK links 20 lines, CLK SEL/INV roles 47 swapped pairs).
- Structural scorecard (mistral `.bt`, `cyclonev_lift_scorecard.py --score-only`): LUT function 270/270, LUT inputs 765/765, FF present/D 175/175, ctl fields 100 %, ff.clk 165/175 (10 missing, all FPLL output counter in `c_pll_vnd_m2d1_1`), pins 520/521, obuf.i 201/202 (PLL lock).
- Functional gate (`cyclonev_lifted_sim_check.py --all`, iverilog, mistral `.bt`): 15 / 18 PASS. FAIL: `c_pll_vnd_m2d1_1` (FPLL CLKOUT not bridged, no clock-tree link for FPLL.000.014), `clock_promotion` (7830 / 32200 samples wrong on 4 pins), `regbank16` (102 / 16100 samples X on 4 pins).
- Same gate on native `.bt`: 14 / 18 (two_clocks fails: the lifter reads the Mistral CLK SEL/INV role names; the native `.bt` has them swapped; pre-existing, not tested on e50f). Lifter now ties `CMUX*:CLKOUT` arc roots (native form) to their pad.
- Not done on this die: compressed images (`COMPRESSED_POSTAMBLES` has e50f only), fuzzing, HMC / PLL beyond the one design, I/O standards.

## Decision needed first
- Whether a Cyclone V is in the hardware. The bench markings settle it: an FPGA marked `5CEFA4U19I7` (Cyclone V E, 5CEA4) would need this work.
- Until then, do not run any of the steps below; they consume Quartus time and RAM.

## How to use it
Run from the repo root with `python3.15t`.

```
python3 -m pytest tests -q                                  # tests
python3.15t scripts/cyclonev_decode.py IN.rbf OUT.bt        # decode a .rbf
python3.15t scripts/cyclonev_unpack.py IN.bin OUT.bt        # native by default; --decoder mistral|--crosscheck
python3.15t scripts/cyclonev_verify_all.py                  # full run incl. die probe + DSP fuzz
python3.15t scripts/cyclonev_reencode.py c_cmp_eq_v95_4 c_shiftreg_v95_4 c_adder_v95_4   # round-trip re-encode (#112)
python3.15t scripts/cyclonev_lifted_sim_check.py --all      # functional gate alone (~2 min), prints the per-kind table
python3.15t scripts/cyclonev_lifted_sim_check.py --all --sim questa   # same gate, build.vo on the vendor libraries
python3.15t scripts/cyclonev_dsp_model_check.py             # our cyclonev_mac model vs the source RTL
python3.15t scripts/cyclonev_dsp_vendor_check.py            # our cyclonev_mac model vs the encrypted vendor atom (Questa)
python3.15t scripts/cyclonev_lifted_sim_check.py <design>   # one design, prints bad pins
```

Rebuild the corpus (needs Quartus; one design at a time; wrap in heavy_guard):
```
python3.15t scripts/cyclonev_corpus_build.py --jobs 1 [--only <design>] [--missing]
```

Relift without Quartus (run on a copy of the DB, one design at a time):
```
cp corpus/cyclonev/corpus.db tmp/corpus.db
PLURIBUS_SQLITE_PATH=$PWD/tmp/corpus.db python3.15t scripts/cyclonev_corpus_relift.py [<design> ...]
PLURIBUS_SQLITE_PATH=$PWD/tmp/corpus.db python3.15t scripts/cyclonev_lift_scorecard.py --label cv_corpus --score-only [--split even|odd]
```

Pipeline on a board config (`boards/<name>/board.toml` with `lifter = "cyclonev"`):
```
python3.15t scripts/run_pipeline.py --board boards/<name> --label <LABEL> --workers 8
```
Use a scratch DB: `PLURIBUS_SQLITE_PATH=<scratch>.db`. Delete it if the schema is stale; derived data has no legacy.

## Rules that still apply
- Missing connection = fault, as bad as wrong. Report matched / (matched + missing + extra + wrong) with raw counts.
- Heavy runs: one Quartus process at a time, `heavy_lock` and `wait_available` from `scripts/heavy_guard.py`.
- No vendor binaries or derived bitstreams are committed. The corpus outputs are gitignored.
- No board-private paths or project names in committed text.

## Not Cyclone V
- The Hantek board (`boards/aw2-2d82auto`) is MachXO2 (LCMXO2-1200). Its status is in `docs/aw2-lift-status.md`.
