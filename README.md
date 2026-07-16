# Pluribus — FPGA RE Static Analysis Engine

Pluribus recovers a full structural netlist from an FPGA bitstream and stores
it in a relational database for fast RE queries.  It supports **SQLite**
(default, no server required) and **PostgreSQL** for CI or shared-server use.

**Runtime:** Python 3.14t (free-threaded / NoGIL) for the parallel BFS stage.

---

## Quick start (SQLite)

```bash
pip install -r requirements.txt

# Load a bitstream into ./pluribus.db
python3.14t load.py --config path/to/device.config --tsv path/to/pins.tsv

# Run BFS reachability
python3.14t reach.py

# Continue through analysis stages
python3.14t reach2.py
python3.14t reach3.py
python3.14t reach4.py

# Generate reports
python3.14t report.py
```

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

| Script | Stage | Description |
|--------|-------|-------------|
| `load.py` | 1 | pytrellis bitstream → database (drops and recreates all tables) |
| `reach.py` | 2 | NoGIL parallel BFS — all-net reachability |
| `reach2.py` | 3 | Net-level reachability summary |
| `reach3.py` | 4 | Structural signal classification |
| `reach4.py` | 5 | Chain extraction + annotation merge |
| `report.py` | — | Main RE report |
| `report2.py` | — | Secondary report |
| `auto_name.py` | — | Auto-naming pass from patterns |
| `tools/build.py` | — | High-level orchestrator (build/init/annotate) |

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
