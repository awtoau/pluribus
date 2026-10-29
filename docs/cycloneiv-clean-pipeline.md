# Cyclone IV GX clean pipeline (started 2026-10-30)

Rebuild of the placement/lift stack from vendor-derived facts only. The layered coordinate model (AFX ladder, descending-x mirror, per-column tables, hop shifts) fitted constants to explain itself and is retired as a source (tag `pre-clean-cycloneiv`).

## Accepted inputs (each with its evidence)

| # | Fact | Source | Evidence |
|---|---|---|---|
| A1 | Routing graph: dests = V(first-dest) + template offsets | `routing.ddb` decode | 14,862,095 edges; fan-in inversion passes; corpus check 99.899 % on 15,474 designs |
| A2 | Asm group bits: flat 31-bit addresses, group = destination's position in the source's fan-out | `asm.ddb` parse + static read of the assembler lookup | 51,565,365 entries; lookup is a pure function of (source id, destination id), no base |
| A3 | LAB LUT-bit address = (hi[r] + dx) * 6154 + lo[c] - dy + 23; hi[r] = 6252 - 70 r; lo[c] = cell of column rank c, paired with LAB columns ascending (rank 0 = lowest X); (dx, dy) = blkrba (x_cum, y_cum) of `RBLUT{k}` | `asmdb` decode; sign of dy and pairing from the oracle | 2,396,160 / 2,396,160 LUT cells vs the oracle-verified LUT law under `address_to_plane` (A4 + A5); constant fitted from one cell, hits on the other 2,396,159 (#165) |
| A4 | Address to image: byte = addr >> 3, bit = addr & 7; no base, band or reversal | static read of `silent_set_bits` | two independent static analyses |
| A5 | sof data bit i to rbf: frame 6153 - (i mod 6154), byte 793 - ((i div 6154) mod 793), bit (i div 6154) div 793; per-die mirror blocks | measured with `quartus_cpf` | bit-exact on vendor and random-plane sofs, 7 GX dies |
| A6 | Geometry: 6344 bits/frame, 8 lanes x 793 rows, 6154 CRAM frames, 39,040,976 bits | `*_pcf.ddb` | matches rbf and sof section length |
| A7 | Name to element: exact equality on (type, x, y, z, index) | static read | not yet tested numerically |
| A8 | Vendor x equals fitter X (no mirror) | identity + A5 on 354 arcs | source and destination tile hit in 354 / 354 |

## Banned inputs

- AFX ladder, `lab_vx` mirror, any (dx, df) / per-column / per-source table, hop override, `EXC4`, shift fits, alias table, learned maps (`li_map`, `phys_map`, `asm_names`), any constant fitted to a single cell.
- Env flags `PLURIBUS_HOP_OVERRIDE`, `PLURIBUS_RELAX_ACTIVE`, `PLURIBUS_R4_COLTABLE`, `PLURIBUS_COORD_V2` and their code paths are removed when the clean gate passes.
- Evidence rows (raw diffs, pairs) stay; derived claim classes 2h, 2h-fd, 2h-col are retired.

## Open (not assumed)

- A3 sign of dy and the `+ 23` constant rest on the oracle fit (one cell), not on a static read of the decode; the decode's own sign convention for `y_cum` is not re-derived.
- Address cells for M9K, MUL, IO; second per-instance vector; exclusion bit group; the 277 calc groups.
- Legacy `.sof` writer not decompiled (identity unverified there).
- No Quartus-built `.sof` with content inside the mirror blocks.

## Plan and exit criteria

1. P1 address engine: pure function (source element, destination element) to rbf cells. Tests: A3 LUT cells 2,396,160 / 2,396,160; A8 arcs 354 / 354 at tile level; `sfl` sofs bit-exact.
2. P2 tracer: RCF name to element (A7), to group, to address, to rbf cells; score per `recovery-process.md` (ambiguous = missing).
3. P3 gate: 76 designs, corrected scoring. Exit: no fault category above the current baseline.
4. P4 retire the old coordinate code in one commit once P3 passes.

## Retirement progress (move order; rollback = tag `pre-clean-cycloneiv`)

- Step 1 done: `scripts/cycloneiv_common.py` (neutral helpers).
- Step 3 done: banned blocks cut from mixed files.
  - `cycloneiv_bit_inventory.py`: classes 2a / 2b removed.
  - `claims_register.py`: 2h / 2h-fd / 2h-col, afx-mirror-v1, phys_map / li_map vote claims, vote-v1 removed.
  - `rebuild_all`, `verify_all`, `profile_stages`, `geo_image_overlay`, `perf_pass_verify`, `pip_table`, `ddb_fanout`, `ddb_blockmap`, `declare_gate`, `mem_report` cut; `image_pass` routing / netlist sections removed.
  - `lifted_sim_check` and `ddb_fanout gt|check` exit with "pending clean P2".
  - Gate script name in `declare_gate` is a TODO for the clean P3 gate.
- Step 4 done: r4 experiments, hop specimens, full/rec/src/sofframe tests, relax analysis, coordv2..v5 removed; summary in `docs/cycloneiv-retired-coordinate-model.md`.
- Step 5 done: `route_learn`, `route_decode`, `route_score`, `phys_trace`, `ddb_trace`, `asm_tables`, `li_map`, `specimens`, `lift_image`, `image_demand`, `asm_decode`, coordv6 / v7 removed.
  - `scripts/cycloneiv_asm_prep.py` keeps the raw record / group / block tables (`prepare`, `icnames`, `programmed`); no coordinate model.
  - `lifters/cycloneiv_lift.py` keeps scan / LUT / FF / Design; routing needs a tracer passed to `lift()` (clean P2 pending).
  - Docs that mention 2a / 2b / `Dec.active` as history point to `docs/cycloneiv-retired-coordinate-model.md`.
- Step 6: learned-map JSONs and derived `tmp/ddb` coordinate-model files removed; env flags and their readers gone. DB rows / claim classes to retire: listed on #165, rebuild happens last.
