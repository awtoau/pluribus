# Legacy lift import — old per-bitstream DB → new per-family DB, then validate (#135, #141)

Goal: resume the parked private-project lift without re-lifting from scratch: IMPORT the existing
per-bitstream database into the family database under the generic schema, register every imported
fact as a claim or evidence row with an explicit `imported` basis, then VALIDATE with the existing
gates. Status is `open` (never verified) until a gate confirms it. Weakest-link rule applies.
Tool: `scripts/import_legacy_lift.py` (generic: any old pluribus SQLite file, any family).

## Inputs

- `--old <file.db>`: the legacy database, read with `sqlite3` directly (old schema; `schema.init()`
  is never run on it). `--label` (one or more `bitstreams.label` rows to import; default all).
- Target: `PLURIBUS_SQLITE_PATH=databases/<family>/<name>.db` (new schema; `schema.init()` runs
  there). The private project's file stays under `databases/machxo2/` (gitignored); its name never
  appears in a committed file or issue.
- Finding (2026-10-29): the private archive DB's only `bitstreams` row was label **V02**
  (`DS1302_V02.bin.config`), not V07; no kept database holds a V07 lift. V02 is no longer a
  reference (Dan): the archive, its imported copy and the earlier V02 pipeline databases were
  all deleted that day. The importer stays as the generic tool (fixture-tested); the V07 import
  waits for a V07 lift (or archive) to exist.
- `--family` (machxo2 / ecp5 / gowin / cyclonev / anlogic) — sets `bitstreams.family` and the
  tier mapping.

## What is imported (table → table)

| old table | new table | note |
|---|---|---|
| bitstreams | bitstreams (+ `family`, `diamond_version` → `toolchain`) | label kept |
| nets, luts, ffs, alu_cells, net_fanout, pad_map, arcs, clock_domains, clock_domain_summary, const_nets, net_stats, lut_symbolic, ebr_buses, cone_hashes, cdc_synchronisers, ebr_init, ebr_init_blocks, efb_config, net_names, cell_names, spi_registers, open_questions | same name | column-by-column; columns the old file lacks → NULL; columns the new schema lacks → dropped and listed |
| efb_ports, ebr_ports, cv_hard_cells | hard_cells + hard_cell_ports | phase F step 4 shape |
| reachability, reachability_rev, pad_ff_influence, ff_cones | NOT copied | derived; re-run `reach.py --replace` + `reach2.py` after the import (minutes) |
| critical_paths, dominators, ff_d_functions, hpbx_branches, mux_cells, patterns/shift_reg_bits | NOT copied | retired or regenerable (`reach3.py`) |

- Integrity gate (automatic): per copied table, old row count == new row count for the label;
  any difference dies. The old file's sha256 + per-table counts + the old schema's column list
  go into one `evidence(kind=vendor-decode, name="legacy import <label>")` row.

## How imported facts are registered

| imported object | claim space / subject | tier (original provenance) | basis string |
|---|---|---|---|
| LUT (cell, init, a..d) | `cell-param` / `LUT:<cell>:init` | `vendor-decoded` (device-db tile decode; MachXO2 lifter) | `imported from legacy lift; decoder = lifters/<family>_lift.py` |
| FF (cell, clk/ce/d/lsr) | `cell-param` / `FF:<cell>` | `vendor-decoded`; `d_fault` set → `unknown(reason=unasked)` | same |
| arc (tile, sink←source) | `pip` / `<sink_wire><-<source_wire>@r,c` | `vendor-decoded` | same |
| pad_map row | `port-map` / `PAD:<pin>` | `measured` when `chip_ref`/`chip_signal` came from the board pins TSV (board measurement), else `vendor-decoded` | `pins.tsv` vs lifter |
| hard cell port | `port-map` / `<cell>:<port>` | `vendor-decoded` (direction as observed in routing) | |
| net_names / cell_names `confidence=confirmed` | `net-attr` / `<net>:name` | `measured` (board trace / pins TSV) | `source` column copied |
| net_names / cell_names `confidence=speculative` | expectation (matcher `human-annotation-v1`, kind statistical) | — (never a claim) | the annotation is a hypothesis awaiting a gate |
| EBR init words, EFB config payload | `cell-param` / `EBR:<block>:init`, `EFB:<sel>:config` | `vendor-decoded` (native 0x72 decode) | |

- One `claims` row per object (~20 k for a 1280-LUT device; bulk insert), one `scopes` row per
  object kind + bitstream (`keys` scope), `claim_evidence(role=direct)` → the import evidence row.
- `lift_provenance`: one row per lut / ff / arc / net / pad with `min_tier`, `min_status=open`,
  `claim_ids`.
- Status `open` for everything; `confidence_basis` carries the original provenance string.

## Validation pass (existing gates; nothing new is invented)

| gate | what it checks | how the result lands | needs |
|---|---|---|---|
| import integrity (above) | counts per table | `gate_runs(script=import_legacy_lift.py)` + `gate_results(category=table)` | nothing |
| `scripts/lift_summary.py --label L --diff <old summary>` | field-by-field change detector vs the legacy file's own summary | `gate_results(category=lift_summary)`: matched = equal fields, wrong = changed | nothing |
| `scripts/check_verilog.py` (yosys lint + LEC vs prior emission) | emitted Verilog still gates (conflicting drivers / loops) | `gate_results(category=verilog_gate)` | yosys |
| private-project Diamond-rebuild LUT INIT multiset (`scripts/aw2_roundtrip.py`, #127/#135) | matched / missing / extra / wrong LUT INITs and registers | `gate_results(category=lut_init, registers)` via `--ingest <report.json>` | Diamond + board artefacts out of tree → Dan's overnight job |
| `scripts/machxo2_gate.py` | device-db oracle (fuzz corpus) — the DECODER the import rests on | `gate_runs` for family machxo2 | Diamond corpus on disk; heavy |

- Confirmations: a gate category at headline 100 % with wrong 0 → `feedback.confirm` on every claim
  under it (by object key where the report names cells; else the class scope); status
  `open` → `confirmed`.
- Mismatches: each wrong / missing object → `feedback.refute` on its claim; the pattern it cites
  (`decoder:<lifter>:<version>`) goes `suspect`, siblings `suspect`, audits queued; the affected
  cones re-open exactly through `lift_provenance.claim_ids` (`provenance/corpus._mark_open`).
- Not validatable by any existing gate (board design has no source: no LEC; EFB input side #100;
  22 stuck registers #127): claims stay `open` with `confidence_basis` naming the reason; they are
  listed by `framework_status.py` as open, never parked (the private corpus is not declared done).

## First run (2026-10-29, the private archive, label V02 — record only; both the archive and the
## imported copy were DELETED the same day on Dan's decision: V02 is not a reference)

- Import: every table count equal (nets 4,262, luts 2,611, ffs 1,112, net_fanout 9,647, pad_map 45,
  arcs 12,326, ebr_init 6,144, net_names 1,962, cell_names 1,720, hard_cells 8, hard_cell_ports 172
  from the old efb_ports 33 + ebr_ports 139); no column dropped. Claims 16,503 (all `open`;
  vendor-decoded 16,221, measured 282 = 45 pads from the board TSV + 237 confirmed net names);
  expectations 3,445 (1,725 non-confirmed net annotations + 1,720 cell names); 1 evidence row.
- `reach.py --replace` 4.4 s, `reach2.py` ~10 s, reach3/reach4 ran clean under a 3 GB lease.
- `--validate` (lift_summary vs the old file): 17 / 18 fields equal; `n_patterns` 12 → 0 — reach3's
  shift-register pass finds no chain on the re-imported netlist where the archive held 12 rows.
  Open finding (a changed detector since the archive was written, or a regression) — to be filed.
- No design oracle exists for this archive (V02 is no longer a reference), so no claim was
  promoted: 16,503 open, 0 confirmed, 0 refuted. The `--ingest` path is exercised by the fixture test.

## Commands

```
PLURIBUS_SQLITE_PATH=databases/machxo2/<private>.db python3.15t scripts/import_legacy_lift.py \
    --old databases/<old>.db --family machxo2 --label <L>            # import + integrity gate + claims
PLURIBUS_SQLITE_PATH=... python3.15t reach.py --bitstream <L> --replace && python3.15t reach2.py --bitstream <L>
PLURIBUS_SQLITE_PATH=... python3.15t scripts/import_legacy_lift.py --validate --label <L> [--ingest tmp/<rebuild>.json]
PLURIBUS_SQLITE_PATH=... python3.15t scripts/framework_status.py
```

- Memory: the import is light (< 1 GB); `--validate` runs under `heavy_guard.lease(3, ...)`
  because reach2 on a 2.6 M-row file peaks at 2.1 GB.
- Order: after phase F (table names above are the post-step-4/5/6 ones).
