# corpus/

- `manifest.json`, `commercial-manifest.json` — ECP5 third-party bitstream manifests (see `docs/ecp5-corpus.md`).
- `cyclonev/` — Cyclone V post-fit oracle corpus (below). Method and results: `docs/cyclonev-postfit-oracle.md`.

## cyclonev/ layout

One flat directory per design. Only `src/` and `design.toml` are tracked; everything else is regenerated.

```
corpus/cyclonev/
  corpus.db                 SQLite DB for the whole corpus (default; $PLURIBUS_SQLITE_PATH overrides)
  <design>/
    design.toml             top, purpose, exercises (feature tags), qsf (extra QSF lines)   [tracked]
    src/*.v                 hand-written source                                              [tracked]
    quartus/                Quartus project (revision "build"), as Quartus left it; .sof deleted
    build.qsf               QSF as used
    postfit.vo              quartus_eda post-fit netlist (atoms, defparams, // Location comments)
    bitstream.rbf           quartus_cpf raw bitstream
    map.rpt fit.rpt asm.rpt eda.rpt build.pin   Quartus reports
    route_report.txt        quartus_sta report_timing -show_routing (script: quartus/route.tcl)
    decomp.bt               mistral-cv decomp of bitstream.rbf
    lifted.v                our lift: load.py (cyclonev lifter) + verilog.py
    compare.json            per-field verdict counts (same data as postfit_compare)
    logs/<step>.log         each tool's own output
```

- Raw tool outputs are never edited; the fixed-name copies at the top level are plain copies.

## Rebuild

- Everything: `python3.15t scripts/cyclonev_corpus_build.py`
- Some designs: `... --only adder12 mult9x9`
- Re-parse + re-compare existing outputs (no Quartus): `... --skip-quartus`
- A rebuild deletes the design's generated files and replaces all of its DB rows.
- Schema changed? Delete `corpus/cyclonev/corpus.db` and rebuild everything (derived data, no migration).
- Log: `tmp/logs/cyclonev_corpus_build.log`. Needs Quartus (`scripts/toolchain.py quartus_bin()`) and mistral-cv.

## Add a design

1. `corpus/cyclonev/<name>/src/<name>.v` (module name = `top`).
2. `corpus/cyclonev/<name>/design.toml`:
   ```toml
   top = "<name>"
   purpose = "one line"
   exercises = ["lut", "dffeas", ...]
   qsf = []          # extra QSF lines, verbatim
   ```
3. `python3.15t scripts/cyclonev_corpus_build.py --only <name>`

Builder options: `--match 'c_*'` (glob), `--missing` (no DB row yet), `--jobs N` (parallel Quartus; DB steps serialised; new builds wait while RAM >= 85%; step limits x N).

## Construct dictionary (`c_<construct>_<variant>_<width>`)

- 222 designs written by `scripts/cyclonev_construct_gen.py` (tracked `src/` + `design.toml`); variants `v95` / `vnd` (Quartus-specific) / `sv`.
- Extra `design.toml` fields: `construct`, `variant`, `width` (ignored by the builder).
- Report: `python3.15t scripts/cyclonev_construct_report.py` -> `docs/cyclonev-construct-dictionary.md`.

## Tables (schema.py)

| table | one row per | columns |
|---|---|---|
| `postfit_builds` | design build | `design` (dir name), `family`, `device`, `top`, `toolchain`, `src_sha256` {file: sha}, `qsf`, `purpose`, `exercises`, `built_at`, `out_dir`, `lift_label` (our lift in `bitstreams`), `status` (`ok` / `fail:<step>`) |
| `postfit_atoms` | placed atom, plus one `type='pin'` row per top-level port | `build`, `name`, `type`, `location`, `loc_kind`, `x`, `y`, `n`, `params` (defparams as JSON; strings unquoted) |
| `postfit_conns` | atom port bit | `build`, `atom`, `port`, `bit` (LSB 0), `direction` (`in`/`out`), `net`, `inverted` (`!` in the .vo), `const` (`0`/`1`/`x`) |
| `postfit_compare` | atom x field | `build`, `atom`, `location`, `field`, `quartus_value`, `lifted_value`, `verdict` |
| `route_hops` | hop of a reported timing path | `build`, `analysis` (`setup`/`recovery`), `path`, `from_node`, `to_node`, `part` (`arrival`/`required`), `hop`, `depth`, `section` (`clock path`/`data path`/...), `driver` (last cell output `atom|port` = the net being routed), `total`, `incr`, `rf`, `type` (`RE`/`IC`/`CELL`/`uTco`), `fanout`, `location`, `loc_kind`, `x`, `y`, `n`, `idx`, `element` |

- Our lift of each build is also in the usual tables (`bitstreams.label = postfit_builds.lift_label`: `luts`, `ffs`, `nets`, `arcs`, `pad_map`).
- Nets: escapes removed, bus bits `name[i]`, `assign` aliases resolved to the driver's net.
- `route_hops` keeps every path's hops (no dedupe): the same routing element appears once per path through it.

## Example queries (`sqlite3 corpus/cyclonev/corpus.db`)

```sql
-- all LUT masks of one design, with placement
SELECT a.name, a.location, json_extract(a.params, '$.lut_mask') AS lut_mask
FROM postfit_atoms a JOIN postfit_builds b ON b.id = a.build
WHERE b.design = 'adder12' AND a.type = 'cyclonev_lcell_comb';

-- every register and its clock net
SELECT b.design, a.name, a.location, c.net AS clk
FROM postfit_atoms a JOIN postfit_builds b ON b.id = a.build
JOIN postfit_conns c ON c.atom = a.id
WHERE a.type = 'dffeas' AND c.port = 'clk';

-- atoms by type per design
SELECT b.design, a.type, count(*) FROM postfit_atoms a
JOIN postfit_builds b ON b.id = a.build GROUP BY 1, 2 ORDER BY 1, 2;

-- comparison verdicts by field, whole corpus
SELECT field, verdict, count(*) FROM postfit_compare GROUP BY 1, 2 ORDER BY 1, 2;

-- who drives and who reads one net
SELECT a.name, a.type, c.port, c.bit, c.direction FROM postfit_conns c
JOIN postfit_atoms a ON a.id = c.atom JOIN postfit_builds b ON b.id = c.build
WHERE b.design = 'counter_en_aclr' AND c.net = 'q[0]~reg0_q';

-- every routing element one net uses (driver = source cell output)
SELECT DISTINCT r.location, r.element FROM route_hops r JOIN postfit_builds b ON b.id = r.build
WHERE b.design = 'counter_en_aclr' AND r.driver = 'q[0]~reg0|q' AND r.type = 'RE';

-- histogram of routing element types, whole corpus (distinct elements)
SELECT element, count(DISTINCT build || ':' || location) FROM route_hops
WHERE type = 'RE' GROUP BY 1 ORDER BY 2 DESC;
```
