# Running the pipeline

**One command, bitstream → queryable netlist + report.** Use
`scripts/run_pipeline.py` — the canonical entry point. It chains every stage,
board-driven, under a single free-threaded interpreter.

```
python3.15t scripts/run_pipeline.py --board boards/<name> --label <LABEL>
```

That's it. It decodes the bitstream, maps IO, loads the netlist, computes
reachability, auto-names, and prints the report — no manual steps, no path
juggling.

## What it runs

| stage | script | does |
|---|---|---|
| unpack | `scripts/trellis_unpack.py` | bitstream `.bin` → `.config` (**native decoder** — lossless, recovers EBR/EFB config) |
| iomap | `scripts/fpga_iomap.py` | `.config` → `.iomap.tsv` (pin↔site) |
| load | `load.py` | `.config` → DB netlist (nets/ffs/luts/pads/EBR/EFB) |
| reach | `reach.py` | all-net BFS reachability (raw-driver NoGIL-parallel) |
| reach2/3/4 | `reach2.py` … | reverse reach, cones, symbolic LUTs, auto-naming |
| report | `report.py` | human-readable status |

`unpack`+`iomap` run only when a raw `.bin` is known **and** its `.config` is
absent; both generators refuse to overwrite, so an existing `.config` is never
clobbered.

## Everything runs under python3.15t (free-threaded NoGIL)

The whole stack is GIL-free: pytrellis is rebuilt for free-threading (pybind11 +
`mod_gil_not_used()`) and `sqlalchemy>=2.1.0b3` keeps the GIL disabled, so one
interpreter serves every stage. Override with `PLURIBUS_PYTHON=<interp>` if
needed.

Prereqs: `python3.15t` on `PATH`; a free-threaded pytrellis build; the tile DB.
`TRELLIS_BUILD`/`TRELLIS_DBROOT` come from the board's `board.toml [trellis]`
table (an explicit environment always wins) — so no paths on the command line.

## Common forms

```
# every bitstream a board declares
python3.15t scripts/run_pipeline.py --board boards/<name> --all

# explicit paths (no board.toml)
python3.15t scripts/run_pipeline.py --label <LABEL> \
    --bin path/to.bin --config path/to.bin.config --pins path/to/pins.tsv

# re-run analysis on an already-loaded label (start at reach)
python3.15t scripts/run_pipeline.py --board boards/<name> --label <LABEL> --skip-load

# tune BFS parallelism
python3.15t scripts/run_pipeline.py --board boards/<name> --label <LABEL> --workers 24
```

Per-stage logs land in `tmp/pipeline_<label>_<stage>.log`.

## Design contract

Every run **drops and rebuilds** all rows for the label — no incremental state,
no stale data. Never treat the DB as a source of truth across runs; always
rebuild. (See `CLAUDE.md` design rules.)

`build.py` is an older orchestrator; its `build` (full-pipeline) path is
superseded by this script. Its `init` (generate a template pins TSV from a
bitstream) and `annotate` (re-import annotations) helpers remain useful.
