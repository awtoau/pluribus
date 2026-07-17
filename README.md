# Pluribus — FPGA RE Static Analysis Engine

Pluribus recovers a full structural netlist from an FPGA bitstream and stores
it in a relational database for fast RE queries.  It supports **SQLite**
(default, no server required) and **PostgreSQL** for CI or shared-server use.

**Runtime:** Python 3.15t (free-threaded / NoGIL); the whole stack is pure
Python — no compiled pytrellis `.so`.

---

## Quick start (SQLite)

```bash
pip install -r requirements.txt

# One command: bitstream → queryable netlist + report + recovered Verilog.
python3.15t scripts/run_pipeline.py --board boards/<name> --label <LABEL>
```

Deliverables land in `out/<LABEL>.v` and `out/<LABEL>-chains.txt`.  See
[docs/pipeline.md](docs/pipeline.md) for stages, board setup, and options.

## Backend selection

| Variable | Default | Purpose |
|---|---|---|
| `PLURIBUS_DB_BACKEND` | `sqlite` | `sqlite` or `postgres` |
| `PLURIBUS_SQLITE_PATH` | `./pluribus.db` | SQLite file path |
| `PGDATABASE` | `fpga_re` | PostgreSQL database name |
| `PGUSER` | `$USER` | PostgreSQL user |
| `PGUNIXSOCKET` | `/run/postgresql/.s.PGSQL.5432` | PostgreSQL Unix socket |

```bash
# Use PostgreSQL instead
PLURIBUS_DB_BACKEND=postgres python3.14t load.py ...
```

---

## Pipeline stages

Canonical entry point: **`scripts/run_pipeline.py`** runs the whole chain
board-driven, one command (see [docs/pipeline.md](docs/pipeline.md)).  The
individual stages, in order:

| Script | Stage | Description |
|--------|-------|-------------|
| `scripts/trellis_unpack.py` | unpack | bitstream `.bin` → `.config` (**native** decoder, no pytrellis) |
| `scripts/fpga_iomap.py` | iomap | `.config` → pin↔site map |
| `load.py` | 1 | `.config` → database (drops and recreates all rows for the label) |
| `reach.py` | 2 | NoGIL parallel BFS — all-net reachability |
| `reach2.py`/`reach3.py`/`reach4.py` | 3–5 | reverse reach, cones, 9-pass auto-naming |
| `auto_name.py` | — | net names from LUT INIT / expression patterns |
| `patterns.py` | — | structural-pattern table the report reads |
| `report.py` | — | human-readable RE report (netlist, clocks, boundary, EBR, patterns) |
| `report_resources.py` | — | resources + **by-peripheral** pin map (ADC/DAC/AFE/SPI), liveness, unknown-bit edges |
| `chains.py` | — | signal-chain report → `out/<label>-chains.txt` |
| `verilog.py` | — | recovered structural Verilog → `out/<label>.v` |
| `tools/build.py` | — | `init` (template pins.tsv from a bitstream) + `annotate` helpers |

---

## Lifters

Device-family lifters translate a bitstream into the generic
`cells` / `nets` / `arcs` schema that the engine ingests.

| Lifter | Family |
|--------|--------|
| `lifters/machxo2_lift.py` | Lattice MachXO2 |
| `lifters/ecp5_lift.py` | Lattice ECP5 (planned) |

---

## Design principles

- **Always-rebuild.** Every run drops and recreates all tables.  No incremental
  state, no stale rows.
- **Fail fast.** Any unexpected condition calls `die()` / `sys.exit(1)`.
  No soft warnings that continue.
- **pg8000 only** for PostgreSQL.  psycopg2 has been removed; psycopg3
  free-threaded support is not yet available (psycopg/psycopg#1095).

---

## Project-specific layers

Device-specific config (pin TSVs, bitstream paths, rebuild scripts) lives in a
separate repo and imports from this package.  This repo is the generic engine
only.
