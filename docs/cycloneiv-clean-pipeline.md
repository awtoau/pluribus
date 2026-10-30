# Cyclone IV GX clean pipeline (started 2026-10-30)

Rebuild of the placement/lift stack from vendor-derived facts only. The layered coordinate model (AFX ladder, descending-x mirror, per-column tables, hop shifts) fitted constants to explain itself and is retired as a source (tag `pre-clean-cycloneiv`).

## Scope assumption (Dan, 2026-10-30)
- Images are assumed to be built by Altera tools: the current Quartus or an earlier version.
- First pass: lift the image to simple Verilog with the current-Quartus-derived decoders.
- Later passes: use the corpus built with older Quartus versions to see what differs by version.
- Not litigated at this stage: who built an image, other tools, forced settings. Status answers stay simple.

## Accepted inputs (each with its evidence)

| # | Fact | Source | Evidence |
|---|---|---|---|
| A1 | Routing graph: dests = V(first-dest) + template offsets | `routing.ddb` decode | 14,862,095 edges; fan-in inversion passes; corpus check 99.899 % on 15,474 designs |
| A2 | Asm group bits: flat 31-bit addresses, group = destination's position in the source's fan-out | `asm.ddb` parse + static read of the assembler lookup | 51,565,365 entries; lookup is a pure function of (source id, destination id), no base |
| A3 | LAB LUT-bit address = `(hi[r] + dx) * 6154 + lo[c] + dy` (vendor formula as read, no sign flip, no constant); hi[r] = 6252 - 70 r; lo[c] = cell of column rank c, paired with LAB columns ascending (rank 0 = lowest X); (dx, dy) = blkrba (x_cum, y_cum) of `RBLUT{k}`; RBLUT index = 15 - INIT bit order | `asmdb` decode; `ASMDB_BLOCK_INFO::calculate_bits_traditional` (libdb_asmdb 0x8e8a4) | 1,023 / 1,023 sites (16,368 cells) vs the blkrba csv; all 16 sign / pairing variants scored, next best 74 / 1,023 (#165) |
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

- A3: the former +3 between decoded pool vectors and the model came from the first pool extraction (list bases chained across BLOCK_INFOs); the clean walk (`asmdb_walk.py`) gives LE_LUT_FUNCTION addresses = model with no constant (E-A3).
- Address cells for M9K, MUL, IO; second per-instance vector; exclusion bit group; the 277 calc groups.
- Legacy `.sof` writer not decompiled (identity unverified there).
- No Quartus-built `.sof` with content inside the mirror blocks.

## Plan and exit criteria

1. P1 address engine: pure function (source element, destination element) to rbf cells. Tests: A3 LUT cells 2,396,160 / 2,396,160; A8 arcs 354 / 354 at tile level; `sfl` sofs bit-exact.
2. P2 tracer (done, `lifters/cycloneiv_clean/tracer.py`): RCF name to element (A7), to group, to address, to rbf cells; score per `recovery-process.md` (ambiguous = missing).
3. P3 gate (`scripts/cycloneiv_clean_gate.py`, baseline in `gate_runs`): rb_000..009 + corpus-rebuild sample, corrected scoring. Exit: no fault category above the current baseline.
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

## Gate regression hygiene (2026-10-30, #165)

- Every recorded gate run stores its member list: `gate_runs.params.members` (design@root names) and the `gate_results` rows.
- `cycloneiv_clean_gate.py --set corpus --root <root> --members-run <run id>` scores exactly the designs of an earlier run (like-with-like fault columns).
- Run 14 (4,007 designs) is recoverable from its `gate_results` rows; run 18 was a superset (4,075 designs, 68 added by corpus growth).

## Register-used, BIM and LOCAL_LINE decodes (2026-10-30, #165)

| Decode | Source | Evidence |
|---|---|---|
| Register used (`reg_used.py`) | asmdb LE_REG_OUT_YGR gi 0 / 1 / 2, LE_USE_SYNC_CLEAR / LOAD, LE_LUT_FUNCTION; used LE_BUFFER from the programmed edges | `scripts/cycloneiv_clean_reg_pairs.py`: 5 LABs x 75 feature sites, 7 pair builds + base, vo ground truth; YGR gi <-> LE_BUFFER parity on rb_000..009 |
| LI -> BIM, VIO data pins (`bim.py`) | MIO_LABLINE_TO_DATA gi 0 (asmdb) + SUB_LOC -> (tile dx, BIM index) | `scripts/cycloneiv_clean_bim_specimens.py`: 6 builds, 24 pads, routing.rcf names the BIM, vo names the pad site |
| LOCAL_LINE -> LAB_CONTROL_MUX | LAB_PIA_TO_INPUT map: 54 inputs = 38 LI + 16 LOCAL_LINE | rb_000..009 GT edges, test_decoders.py |
