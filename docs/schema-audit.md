# Schema audit — every table in `schema.py`, 2026-10-29 (#141)

Phase A of the provenance framework. Read-only inventory; nothing applied. Target schema:
[provenance-schema.md](provenance-schema.md). Row counts from `databases/*.db` + `./pluribus.db`,
opened read-only (python sqlite3, `mode=ro`); writers/readers from a grep of 317 `.py` files
(root, `scripts/`, `lifters/`, `tests/`, `tools/`, `diamond-fuzz/`, `native_trellis/`, `boards/`;
`.claude/worktrees`, `sources/`, `debris/` excluded).

## Databases on disk

| DB | size | bitstreams (device) | notable rows |
|---|---|---|---|
| aw2.db, aw2_final_check.db, aw2_merge_verify.db, aw2_verify.db | ~620 MB each | 1 LCMXO2-1200 each | identical counts: reachability + reachability_rev 2.65 M each, ff_cones 1.14 M, dominators 303 k, critical_paths 220 k, arcs 12 k, luts 2,611, ffs 1,108 — three of the four are duplicates |
| the private-project check DB | 683 MB | 1 LCMXO2-1200 | reachability 2.84 M, ff_cones 1.27 M, dominators 402 k, critical_paths 267 k |
| repl.db | dropped 2026-10-29 | non-DJI real-design lift; regenerable on demand (`regen_databases.py --run repl`) | was reachability 106 k, arcs 6,281, luts 815 |
| fnirsi.db | dropped 2026-10-29 | non-DJI real-design lift; regenerable on demand (`regen_databases.py --run fnirsi`) | was reachability 1.93 M, ff_cones 916 k, arcs 37 k, alu_cells 192, ebr_ports 840 |
| fuzz_rebuild.db | 22 MB (regenerated 2026-10-29: 25 MB, 2,779 labels, all load; the one earlier fail was a transient mid-edit of `load.py`, passes on re-run) | 2,705 LCMXO2-1200 | pad_map 135 k, arcs 69 k, nets 32 k |
| cyclonev_merge_verify.db, cyclonev_verify_all_padmap.db | 35 MB | 1 5CEBA4U19C8 | net_fanout 167 k, nets 144 k, arcs 70 k, luts 33 k, ffs 11.5 k |
| image_g.db | 77 MB | 1 **5CEBA4U19C8** | same counts as the cyclonev DBs + reachability 168 k — README says "EP4CGX150 image lift"; the device column and the counts say Cyclone V. README row is wrong (or the file is misnamed) |
| fuzz_full2.db | 25 MB | none | NOT a schema.py DB: `fuzz_wires` 114 k, `fuzz_runs` 1,142, `synth_logs`, `fuzz_toolchain_versions` — owned by `tools/fuzz_machxo2_full.py`, `tools/run_machxo2_fuzz.py`, `tools/build_all.py` (DDL outside schema.py: rule violation) |
| ./pluribus.db | 6.6 MB | 0 | postfit_builds 8,032 (Cyclone IV specimen corpus index); all else 0 |
| pluribus.db.stale-schema-20261028 | 0.6 MB | 0 | empty |

- Every DB holds exactly ONE device (fuzz_rebuild: one device, 2,705 labels). This is the
  intended shape (Dan, 2026-10-29): one file per family / product / project, all from the same
  `schema.py`; cross-DB questions ATTACH (`dbtools.py`). Not a finding.
- Old snapshots lack 8–20 of the 55 tables (pre-#141 columns); `schema.init()` dies on drift,
  so none can be opened by current code without a rebuild. Consistent with "derived artefacts
  have no legacy", but it makes the kept DBs read-only archives, not working databases.
- `fuzz_full2.db` row counts and `image_g.db` README row need correcting in `databases/README.md`.

## Table inventory

Columns: users = scripts that write (W) / read (R); rows = max over the DBs above; verdict =
keep / generalise / merge / retire. Cost = what regeneration costs if the table changes shape.

### 1. Netlist layer (per-bitstream lift output; `load.py` writes all)

| table | families | W / R | rows | verdict | evidence / notes |
|---|---|---|---|---|---|
| bitstreams | all | load.py / ~29 | 2,705 | **generalise** | `device`/`package` free text; `diamond_version` is Lattice-specific (Gowin/Quartus versions go in the same column by convention). Needs `family` FK + `toolchain` rename. Cost: none (column add) |
| nets | all | load.py / 10 | 144 k | keep | |
| ffs | all | load.py / 17 | 11.5 k | keep | `dtype`/`d_fault` are generic enough; `lsr` is Lattice vocabulary (Gowin uses it too) |
| luts | all | load.py / 13 | 33 k | keep | `e`/`f` for Cyclone V ALM; fine |
| alu_cells | gowin | load.py / 3 | 192 | keep | Gowin-only by content, generic by shape (any carry cell) |
| mux_cells | ecp5 (intended) | load.py / **none** | 0 everywhere | **retire → merge into a generic `cells` table** | write-only, never populated |
| net_fanout | all | load.py / 9 | 167 k | keep | the connectivity index everything reads |
| pad_map | all | load.py / ~23 | 135 k | keep | `chip_ref/chip_pin/chip_signal` are board data (boards/); acceptable since the DB mixes board + engine by design |
| efb_ports | machxo2 | load.py / 10 | 697 | **generalise** | MachXO2 EFB only; Gowin/ECP5/Cyclone hard blocks use `ebr_ports`/`cv_hard_cells` instead — three shapes for "hard-block port → net" |
| ebr_ports | machxo2, gowin | load.py / 7 | 1,261 | **generalise** | same concept as efb_ports + cv_hard_cells.data.pins |
| ebr_init, ebr_init_blocks | machxo2 | load.py / 2 | 6,144 | keep | ECP5/Gowin BRAM init would reuse as-is |
| efb_config | machxo2 | load.py / 2 | 74 | keep | family-specific payload, generic shape (sel/kind/payload) |
| clock_domains | all | load.py / 4 | 2,811 | keep | |
| anlogic_tiles | anlogic | load.py / 1 test | 0 everywhere | **generalise** | per-tile CRAM occupancy is useful for every family (the Cyclone IV inventory recomputes it in numpy); rename `tiles`, add `family` |
| cv_hard_cells | cyclonev | load.py / 2 | 0 everywhere (image_g lacks the table) | **generalise** | `{cell, kind, data JSON}` is the right generic shape for every hard block; efb_ports/ebr_ports could be views of it |
| arcs | all | load.py / 4 | 70 k | keep | `tile_row/col` + `sink_gx/gy/gid` are the only per-family coordinates; Cyclone IV will need (frame, v)-free tile addressing — fine as-is |
| hpbx_branches | machxo2 | load.py / **none** | 4,450 | **retire** | write-only; the clock-tree branch info is recomputed by reach4/clock_domain_summary |
| clock_domain_summary | all | load.py / 3 | 2,704 | keep | `hpbx_track`/`pll_output` are MachXO2 names; nullable, tolerable |

### 2–5. Analysis layers (reach / reach2 / reach3 / reach4 outputs)

| table | W / R | rows | verdict | notes |
|---|---|---|---|---|
| reachability, reachability_rev | reach, reach2 / 8 | 2.84 M each | keep | 76 % of every big DB; derived, regenerable |
| pad_ff_influence | load, reach / 2 | 3,144 | keep | |
| patterns, shift_reg_bits | patterns.py, reach3 / 3 | 12 / 0 | **rename** | `patterns` collides with the provenance `claim_patterns` concept; it holds NETLIST structure patterns (shift registers). Rename `netlist_patterns` when next regenerated; new code must not add a second `patterns` |
| ff_d_functions | reach3 / **none** | 11.5 k | **retire** | write-only |
| net_names, cell_names | load, reach4, annotate / 8 | 2 k | keep | `confidence` free text (`speculative`/`confirmed`) = an un-tiered claim; the knowledge-layer confidence should become a claim tier (see target schema) |
| spi_registers, open_questions | annotate / 3 | 19 / 2 | keep | board knowledge, used by sim_no_ip |
| ff_cones | reach2 / reach3 | 1.27 M | keep | |
| critical_paths, dominators | reach2 / **none** | 267 k / 402 k | **retire** | write-only, 15 % of each big DB |
| lut_symbolic, clock_crossings, ebr_buses, net_stats, cone_hashes, const_nets | reach3 / 2–4 each | 33 k / 0 / 840 / 144 k / 11.5 k / 211 | keep | clock_crossings is 0 rows everywhere but is read by reach4/report — leave |
| cdc_synchronisers | reach4 / report | 28 | keep | |

### 6. Device data / corpus / fuzz

| table | W / R | rows | verdict | notes |
|---|---|---|---|---|
| device_fingerprints | cyclonev_die_probe / **none** | 0 everywhere | **retire** | write-only, never populated; its purpose (identify device from image header) belongs to a `devices` registry row |
| cv_dies, cv_pram_strips | cyclonev_db_import / rust bluebird | 0 in every kept DB | keep (vendor data) | Python has no reader; Rust does. The `devices` registry should carry die geometry generically; cv_* stay as the Cyclone V detail tables |
| cv_route_muxes, cv_route_lines, cv_route_drivers, cv_p2r, cv_p2p | cyclonev_db_import_routes (raw f-string SQL) / rust | 0 in kept DBs | keep (vendor data) | raw `DELETE`/`INSERT` strings bypass SQLAlchemy Core — convert when touched |
| cv_block_muxes | cyclonev_db_import_blockmux (raw SQL) / blockmux_fuzz | 0 | keep | same |
| postfit_builds | corpus_register, cyclonev_corpus_build, postfit_compare / 8 | 8,032 | **generalise → `corpus_builds`** | already multi-family (`family` column) but named for Quartus post-fit; Lattice corpora (diamond-fuzz 2,779, constructs, coverage, globals; ECP5 Diamond builds) are NOT registered — their index is directories + `tests/baselines/ecp5_oracle.json`. The gate tables in the target schema cite this table for every family |
| postfit_atoms, postfit_conns | cyclonev_vo_parse / 4 | 0 | keep | vendor oracle netlist, Quartus-shaped; Lattice oracle is `.nmc`/`oracle.json` on disk, never in the DB — asymmetric but not wrong |
| postfit_compare | cyclonev_postfit_compare / 2 | 0 | **generalise → `gate_results`** | per-field verdict rows (MATCH/MISMATCH/LIFT_MISSING/QUARTUS_ONLY) = exactly the scoring-faults categories; the ECP5/MachXO2 gates keep the same verdicts in JSON files only |
| route_hops, rcf_routes | cyclonev_route_parse, rcf_parse / 4 | 0 | keep | oracle routing (vendor-sourced) |
| rcf_fuzz_bits | cyclonev_rcf_fuzz / **none** | 0 | **retire → `evidence`** | write-only; one row = one specimen diff (`changed_bits`, control vs variant) — that IS an `evidence(kind=specimen-pair)` row with a Cyclone V-specific shape |

## Cross-cutting findings

1. **Provenance is a string or absent.** `net_names.confidence`/`source`, `cell_names.confidence`
   (free text), phys_map `provenance: specimen`, `LEDGER_TIER` hard-coded in the inventory script,
   gate verdicts in JSON files. No table says which evidence a lifted object rests on.
2. **Three shapes for "hard block port → net"** (efb_ports, ebr_ports, cv_hard_cells.data) and
   two for "specimen diff" (rcf_fuzz_bits, the 31 evidence JSONs under `evidence/cycloneiv/`).
3. **Corpus/gate state is per-family ad hoc**: Cyclone IV/V in `postfit_builds`; ECP5 in
   `tests/baselines/ecp5_oracle.json` + `corpus/ecp5/diamond-oracle/*/compare.json`; MachXO2 in
   `tmp/ocmp/<tag>/*.json` (disposable!); Gowin in `gowin_lec.py` yosys equivalence output. No
   table answers "does family F pass its corpus at this commit".
4. **Family-specific tables are named by family** (`cv_*`, `anlogic_tiles`, `efb_*`, `hpbx_*`),
   generic ones are not. Vendor device data is the one place a family prefix is right (it IS
   family-shaped); lift output and corpus state are not.
5. **DDL outside schema.py**: `tools/fuzz_machxo2_full.py` and friends own four tables in
   `fuzz_full2.db` (fuzz_wires, fuzz_runs, synth_logs, fuzz_toolchain_versions).
6. **Raw SQL strings** in the three `cyclonev_db_import*` scripts (f-string DELETE/INSERT).
7. **Write-only tables** (7): mux_cells, ff_d_functions, critical_paths, dominators,
   hpbx_branches, device_fingerprints, rcf_fuzz_bits. critical_paths + dominators are ~670 k
   rows per big DB with no reader.
8. **Missing indexes**: `net_fanout(bitstream, cell)` (undriven_classify / chains look up by
   cell), `arcs(bitstream, sink_wire)`, `ebr_ports(bitstream, net)`, `luts(bitstream, z)`. Not
   measured; listed from the readers' WHERE clauses.
9. **Naming**: `patterns` (netlist) vs the provenance `claim_patterns`; `bitstream` FK column vs
   `build` FK column for the same role; `tile_row/tile_col` (arcs) vs `x/y` (postfit_atoms,
   rcf_routes) vs `rn_x/rn_y` (cv_*) — three spellings of a tile coordinate.
10. `bitstreams.diamond_version` is the toolchain version for every family (misnamed).

## Verdict summary

| verdict | tables |
|---|---|
| keep (33) | nets, ffs, luts, alu_cells, net_fanout, pad_map, ebr_init, ebr_init_blocks, efb_config, clock_domains, arcs, clock_domain_summary, reachability, reachability_rev, pad_ff_influence, net_names, cell_names, spi_registers, open_questions, ff_cones, lut_symbolic, clock_crossings, ebr_buses, net_stats, cone_hashes, const_nets, cdc_synchronisers, cv_dies, cv_pram_strips, cv_route_muxes, cv_route_lines, cv_route_drivers, cv_p2r, cv_p2p, cv_block_muxes, postfit_atoms, postfit_conns, route_hops, rcf_routes |
| generalise (7) | bitstreams (+family, toolchain), efb_ports + ebr_ports + cv_hard_cells (→ `hard_cells` + `hard_cell_ports`), anlogic_tiles (→ `tiles`), postfit_builds (→ `corpus_builds`), postfit_compare (→ `gate_results`) |
| rename (1) | patterns → netlist_patterns (with shift_reg_bits) |
| retire (7) | mux_cells, ff_d_functions, critical_paths, dominators, hpbx_branches, device_fingerprints, rcf_fuzz_bits (→ evidence) |
| new (provenance framework, 20) | see provenance-schema.md |

## Cost of change

- **Additive tables (phase C): zero.** `schema.init()` creates them in any DB; existing
  pipelines untouched.
- **Retiring write-only tables**: delete the table + the writer's insert block. No regeneration;
  kept DBs keep the orphan tables (harmless, `_assert_no_drift` only checks declared columns).
- **Generalising bitstreams / hard-cell / tiles tables**: every lift DB must be regenerated —
  `schema.init()` dies on missing columns. Measured regeneration cost (pipeline load → reach4):
  V02 ≈ 2–3 h (reachability 2.6 M rows), FNIRSI ≈ 2 h, fuzz_rebuild (2,705 labels) ≈ 4–6 h of
  Diamond-free lifting, Cyclone V image_g/cyclonev_* ≈ 1 h each. ~10–14 h of machine time in all,
  no vendor builds. The four aw2 snapshots and the private-project check DB were all V02 lifts
  (the check DB's only label was V02): deleted 2026-10-29 on Dan's decision (V02 is not a
  reference), nothing regenerated; a V07 lift will be imported via docs/legacy-import.md when
  one exists.
- **Renaming postfit_builds → corpus_builds**: `./pluribus.db` only (8,032 rows, rebuilt by
  `corpus_register.py` in seconds). The 8 readers change one identifier.
- **postfit_compare → gate_results**: 0 rows anywhere; code change only.

## Destructive-cleanup proposal (needs Dan's go; NOT applied)

1. Drop write-only tables: `mux_cells`, `ff_d_functions`, `critical_paths`, `dominators`,
   `hpbx_branches`, `device_fingerprints`; delete their writer blocks in `load.py`, `reach2.py`,
   `reach3.py`, `scripts/cyclonev_die_probe.py`.
2. Drop `rcf_fuzz_bits`; `scripts/cyclonev_rcf_fuzz.py` writes `evidence(kind=specimen-pair,
   family=cyclonev)` instead.
3. Rename `postfit_builds` → `corpus_builds`, `postfit_compare` → `gate_results` (the new
   gate_results table in phase C already covers it; delete postfit_compare and point
   `cyclonev_postfit_compare.py` at gate_results).
4. Merge `efb_ports`, `ebr_ports`, `cv_hard_cells` → `hard_cells` (cell, kind, params JSON) +
   `hard_cell_ports` (cell, port, direction, net, role). Regenerate aw2.db, fnirsi.db, repl.db,
   fuzz_rebuild.db, image_g.db.
5. Rename `anlogic_tiles` → `tiles` (+ family); `patterns` → `netlist_patterns`.
6. `bitstreams`: add `family` (FK families.id), rename `diamond_version` → `toolchain`.
7. Move `fuzz_full2.db`'s four tables into schema.py or delete the DB (its content is
   superseded by fuzz_rebuild.db + corpus/machxo2/diamond-fuzz).
8. `databases/README.md`: fuzz_full2 is not a schema.py DB; delete
   aw2_final_check/aw2_merge_verify/aw2_verify (byte-identical row counts to aw2.db); move the
   files into `databases/<family>/` per the new layout (image_g row already corrected).
9. Convert the raw-SQL `cyclonev_db_import*` writers to SQLAlchemy Core.
10. Add the four indexes in finding 8 after measuring the readers.
