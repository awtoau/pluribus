# aw2 board lift status (label V07, LCMXO2-1200)

- Command: `PLURIBUS_SQLITE_PATH=<scratch>.db python3.15t scripts/run_pipeline.py --board boards/aw2-2d82auto --label V07 --workers 8`
- Field-by-field diff for regression: `scripts/lift_summary.py --label V07 --out X.json` then `--diff X.json`.
- Scoring rule: missing connection = fault (CLAUDE.md "Scoring faults"). Counts below are raw.

## Baseline (main 0bb7c5378, 2026-10-24)

| | V07 | V02 |
|---|---|---|
| LUTs (pseudo-LUT count, device has 1280) | 2636 | 2611 |
| FFs | 1093 | 1112 |
| nets | 4304 | 4262 |
| EFB ports in / out | 21 / 9 | 23 / 10 |
| EFB config | SPI sel 0x54 | 2 blocks |
| yosys gate | PASS | PASS |
| no-driver wires (gate) | 270 | 231 |
| DB-level undriven nets (no LUT/FF/EFB/pad driver) | 528 | 490 |
| conflicting drivers / comb loops / reg loops / other warn | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| sim_no_ip.py | COMPILE FAILS (`efb_inst.wb_poke` unscoped, instance is `dut.efb_inst`) | not run |

## Round-trip depth (#84)

- `scripts/machxo2_roundtrip.py` (known-source scope RTL, not the board bitstream): bounded miter PROVEN to cycle 52, DIVERGES at 53 (first serialised readback bit).
- cs_n high: PROVEN 80 cycles. DPRAM forced 0: still diverges (readback datapath gap).
- Board bitstream has no source: no LEC possible. Structural round-trip = lifted Verilog -> Diamond -> decode -> compare (not yet run on the board design).

## Step 2: EFB config + inputs (#100)

- Inputs were already lifted (21 in / 9 out, unchanged). New: oracle comparison of the input side (docs/efb-config.md): 20/(20+0+1+0) pins match Diamond; the 1 fault is WBCLKI (global spine, #109).
- Board-design inputs with no driver in the lift: JWBCLKI (alias of the spine clock input, driven by testbench), JSPISCSN (on `G_HSBX0201`, #109).
- EFB instance now carries decoded attributes (`EFB #(.EFB_SPI("ENABLED"), .SPI_MODE("SLAVE"), ...)`); config bits outside the oracle table print UNEXPLAINED (none in V07/V02).
- Lifter regression: V07 and V02 summaries differ only in `v_bytes`/`v_sha256` (EFB parameter block).
