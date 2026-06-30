# Pluribus — agent instructions

## What this repo is

Pluribus is a generic FPGA reverse-engineering static analysis engine.  It
recovers a full structural netlist from a bitstream and stores it in a
relational database for fast RE queries.

The engine is backend-agnostic.  **SQLite is the default** (no server needed).
PostgreSQL is supported for CI and shared-server use.

## Critical constraint

`/mnt/2tb/git/awto-2000/` is a **live RE project**.  Never modify, move, or
delete any files there.  All work in this repo was *copied* from awto-2000;
edits to awto-2000 must be made there separately.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PLURIBUS_DB_BACKEND` | `sqlite` | `sqlite` or `postgres` |
| `PLURIBUS_SQLITE_PATH` | `./pluribus.db` | SQLite file path |
| `PGDATABASE` | `fpga_re` | PostgreSQL DB name |
| `PGUSER` | `$USER` | PostgreSQL user |
| `PGUNIXSOCKET` | `/run/postgresql/.s.PGSQL.5432` | PostgreSQL Unix socket |

## Database driver

**pg8000 only** for PostgreSQL — pure Python, safe in python3.14t NoGIL
threads.  psycopg2 has been removed from this system.  psycopg3 free-threaded
support is not yet available (psycopg/psycopg#1095).  Do not add psycopg2 or
psycopg3 back.

## Schema

Defined in `schema.py` as SQLAlchemy Core tables.  All TEXT[] and JSONB
columns are stored as JSON for cross-dialect portability.  BigInteger PKs
use `Integer` so SQLite autoincrement works correctly (SQLite only
autoincrements `INTEGER PRIMARY KEY`, not `BIGINT PRIMARY KEY`).

Call `schema.init()` before first use to create all tables (IF NOT EXISTS).

## DB access layers

- **`db.connect()`** — psycopg2-compatible shim (all scripts except reach.py).
  Returns a `_Conn` with `.cursor()`, `.commit()`, `.close()`.
  Cursor supports `.execute(sql, params)` with `%s` placeholders,
  `.executemany()`, `.fetchall()`, `.fetchone()`, `.rowcount`.
- **`db.execute_values(cur, sql, rows)`** — replacement for
  `psycopg2.extras.execute_values`.  Use it everywhere `%s` appears in a
  VALUES clause.
- **`db.connect_threadsafe()`** — raw per-thread connection for `reach.py`
  NoGIL workers.  Returns `pg8000.native.Connection` or `sqlite3.Connection`
  depending on backend.  Never share between threads.

## Pipeline stages (in order)

```
python3.14t load.py  --label V07 --config path/to.bin.config --pins pins.tsv
python3.14t reach.py [--bitstream V07] [--workers N]
python3     reach2.py [--bitstream V07]
python3     reach3.py [--bitstream V07]
python3     reach4.py [--bitstream V07]
python3     report.py [--bitstream V07]
```

`reach.py` requires python3.14t (free-threaded NoGIL).  All other scripts
work with regular python3.

## Tests

```
python3 -m pytest tests/test_sqlite.py -v
```

No server needed — runs entirely against a temp SQLite file.

## Lifters

Device-family lifters live in `lifters/`.  Each translates a bitstream into
the generic `cells`/`nets`/`arcs` schema.

- `lifters/machxo2_lift.py` — Lattice MachXO2 (production)
- `lifters/ecp5_lift.py` — Lattice ECP5 (planned, issue #9)

The parametric lifter (`lifters/trellis_lift.py`, issue #9) will take a
`family` argument so one codebase handles MachXO2, ECP5, and future families.

## Design rules (do not change)

- **Always-rebuild per bitstream:** every run deletes all rows for the given
  label and reinserts from scratch.  No incremental state, no stale rows.
- **die() / hard exit:** any unexpected condition calls `db.die(msg)`.
  Never replace with a soft warning.
- **No psycopg2:** removed from this system.  pg8000 is the only PG driver.
- **schema.py owns all DDL:** do not create tables in scripts via raw
  `CREATE TABLE` SQL.  Add them to `schema.py` and call `schema.init()`.
