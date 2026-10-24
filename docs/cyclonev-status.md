# Cyclone V (e50f / 5CEBA4U19C8): parked status

Parked 2026-10-24 until we know whether a Cyclone V part is needed. Everything below is on `main`.

## Where it is
- **Corpus:** 237 Quartus-built designs (236 + `c_latch_v95_1`), `corpus/cyclonev/<design>/`.
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

## Status (measured 2026-10-24, corpus of 237)
- **Functional (lifted Verilog simulated vs Quartus `build.vo`, `scripts/cyclonev_lifted_sim_check.py --all`):**
  - Designs: 165 pass, 47 fail, 24 not covered (RAM 22, DSP 2), 1 not built (`c_latch_v95_1`).
  - Output samples, covered designs: matched 3441733 / 3804461 (90.5%); wrong 362728, missing 0.
  - By kind: combinational 92/92, carry 18/18, registered + carry 15/15, registered 40/87.
  - All 47 failures: registers with an enable, async clear, sync clear or negedge clock. The
    lifter recovers these controls (`Design.ffs[i]["ctl"]`) but `ffs` / `verilog.py` have no columns
    for them, so the register is emitted undriven. Next step; not claimed.
  - Model check (Quartus netlist + our cell models vs `src/`): 191 ok, 0 wrong.
  - Before the polarity fix (2026-10-24): 14 pass, 198 fail; matched 2114047 / 3804461 (55.6%).
- **Structural (lifter fields vs Quartus post-fit, `scripts/cyclonev_lift_scorecard.py`), matched / total:**
  - The compare applies Quartus's `!` flags, so LUT masks and output buffers are scored as functions of
    the nets (before this, the scorecard read 100% while lifted.v was functionally wrong).
  - LUT function 3288 / 3288 (236 constant-0 cells excluded with a stated rule); LUT inputs 11093 / 11093
  - arithmetic function 741 / 741; carry and share 431 / 431
  - flip-flop control sources 2794 / 2794 each (present, D, clock, edge, domain, clear, enable, sync-clear, load):
    the source is recovered; the emitted Verilog does not use clear / enable / sync-clear / negedge yet (above).
  - pins 4556 / 4556; output buffers 1556 / 1556. Extra and wrong are 0 in every field.
- **Native decoder:**
  - CRAM frames: 1,170,088, all CRC-16 valid.
  - Routing pips: 39,550 / 39,550 against RCF. About half of RCF edges have no native node and are unscored.
  - LUT masks: 98.5%. Flip-flop presence: 98.5%. Pin use and direction: 97.6%.
  - Held-out split (family-level): routing 100% on both halves.
- **Verification:** `scripts/cyclonev_verify_all.py --skip-die-probe --skip-dsp-fuzz` FAILS by design: stage 5 (lifted sim, blocking) fails on the 47 register designs above. Selftest and pad map pass; baseline on `regbank16`: 61 LUTs, 64 FFs, 139 nets, 608 arcs, 19 pads.
- **Tests:** `python3 -m pytest tests -q` passes (202).

## Still open
1. ~~`_lut_self_latch()`~~ closed 2026-10-24: removed. `c_latch_v95_1` (Quartus-built) showed it wrong (q1 never sets, q2 refused, oscillator emitted as a latch). Detail: `docs/cyclonev-postfit-oracle.md` "Self-feeding LUT latch".
   - Item 9 below (port-space masks, pad inverters): closed.
2. **Memory LABs (MLAB):** RAM and ROM halves are not lifted. In the four `c_ram_vnd_mlab_*` designs, 8 CRAM bits are unclaimed and 224 frames fail their EDCRC.
3. **Clock tree:** validated on two corpus pads (K17, L17) only. PLL inputs, HR/VR muxes and other clock paths have no evidence.
4. **Tables without an oracle:** PLL, HMC, I/O standards and M10K widths still come from Mistral's data.
5. **Flip-flop controls and option RAM:**
   - Closed 2026-10-24: `sclr` 2794/2794 and `sload` 2794/2794 (the "93-97%" figure was stale); feedback-only flip-flops are recovered (`ff.present` 2794/2794, extra 0; rule: `uses_fb and FEEDBACK_SEL == slot` in `lifters/cyclonev_lift.py`).
   - `sload` as a signal stays unclaimed: all 2794 Quartus registers tie `sload` to gnd (1344) or vcc (1450). The lifter's const rule (1 iff pin-fed) is the only rule the corpus supports.
   - Not closed: CRAM option bit 6.3 and the CvP bit. `OPT_B` is `ffffff40.2dffffff` in all 237 designs, so the corpus cannot name either bit; naming needs a knob build.
6. **Re-encode check:** a Quartus rebuild of a one-LUT-bit Verilog change, compared against the edited bitstream, has not been done.
7. **Dies:** only e50f is exercised. The native decoder refuses sx50f, sx120f and any HPS die.
9. ~~**lifted.v polarity**~~ closed 2026-10-24: LUT tables are over the nets, pad output inverters are NOT rows (rule: `docs/cyclonev-postfit-oracle.md` "Polarity"). Gate: `scripts/cyclonev_lifted_sim_check.py --all`, stage 5 of `cyclonev_verify_all.py`.
10. **Register controls in lifted.v:** enable, async clear, sync clear and negedge registers are emitted undriven (47 designs fail the sim gate). Needs `ffs` columns (schema decision) or a Cyclone V register emitter.
11. **Sim gate not covered:** RAM (`cyclonev_ram_block`, `cyclonev_mlab_cell`) and DSP (`cyclonev_mac`): no simulation model (vendor atoms encrypted). No PLL in the corpus.
8. **Not scored:** I/O drive, slew and standard (no variation in the corpus), DSP beyond MODE, MLAB RAM bits.

## Decision needed first
- Whether a Cyclone V is in the hardware. The bench markings settle it: an FPGA marked `5CEFA4U19I7` (Cyclone V E, 5CEA4) would need this work.
- Until then, do not run any of the steps below; they consume Quartus time and RAM.

## How to use it
Run from the repo root with `python3.15t`.

```
python3 -m pytest tests -q                                  # tests
python3.15t scripts/cyclonev_decode.py IN.rbf OUT.bt        # decode a .rbf
python3.15t scripts/cyclonev_unpack.py IN.bin OUT.bt        # native by default; --decoder mistral|--crosscheck
python3.15t scripts/cyclonev_verify_all.py --skip-die-probe --skip-dsp-fuzz
python3.15t scripts/cyclonev_lifted_sim_check.py --all      # functional gate alone (~60 s)
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
