# Pluribus — SQLite/PostgreSQL dual-backend migration handoff

## Goal

Migrate the Pluribus FPGA RE analysis engine from PostgreSQL-only to a dual
SQLite / PostgreSQL backend, selectable at runtime.  SQLite is the new default
for local development (no server required).  PostgreSQL remains supported for
CI, shared servers, and large-device runs.

## Repository

- **Source of truth:** `/mnt/2tb/git/awto-2000/fpga/pluribus/` (current engine)
- **Target repo:** `awtoau/pluribus` (GitHub private) — working copy at
  `/mnt/2tb/git/pluribus/` (currently empty — only the git remote is set up)
- **Move:** the entire `fpga/pluribus/` tree should become the root of the
  `awtoau/pluribus` repo.  The project-specific layer
  (`fpga/pluribus_awto-2000/`) stays in `awto-2000` and adapts to import from
  the new package.

---

## Current architecture

### Files (all in `fpga/pluribus/`)

| File | Lines | Role |
|------|-------|------|
| `db.py` | 49 | Connection helpers (`connect()` → psycopg2, `connect_pg8000()` → pg8000), `die()`, shared constants |
| `load.py` | 1107 | Stage 1: pytrellis bitstream → PostgreSQL. Drops+recreates all tables each run. |
| `reach.py` | 304 | Stage 2: NoGIL parallel BFS (python3.14t, 24 threads) using `pg8000.native` |
| `reach2.py` | 384 | Stage 3: net-level reachability summary |
| `reach3.py` | 1189 | Stage 4: structural signal classification |
| `reach4.py` | 1202 | Stage 5: chain extraction + annotation merge |
| `patterns.py` | 193 | Pattern matching on classified nets |
| `chains.py` | 431 | Chain report output |
| `build.py` | 544 | High-level build orchestrator |
| `report.py` | 1086 | Main RE report generator |
| `report2.py` | 317 | Secondary report |
| `auto_name.py` | 351 | Auto-naming pass from patterns |
| `fuzz.py` | 180 | Synthetic test bitstream checker |
| `verilog.py` | 763 | Verilog netlist helpers |

### Database

- **Engine:** PostgreSQL (local Unix socket, db=`fpga_re`, user=`dan`)
- **Current driver situation (being simplified):** `db.py` has two connect
  functions — `connect()` using psycopg2 and `connect_pg8000()` using pg8000.
  psycopg2 has been **removed from this system** and will not be reinstalled.
  The split existed only because psycopg2 re-enables the GIL inside its C
  extension, making it unsafe in python3.14t NoGIL threads — pg8000 is pure
  Python and has no GIL interaction at all.  **pg8000 is the correct and only
  postgres driver going forward.**
- **Connection config** (from `db.py`):
  ```python
  _DB   = os.environ.get("PGDATABASE",   "fpga_re")
  _USR  = os.environ.get("PGUSER",       os.environ.get("USER", "dan"))
  _SOCK = os.environ.get("PGUNIXSOCKET", "/run/postgresql/.s.PGSQL.5432")
  _DSN  = os.environ.get("PLURIBUS_DSN", f"dbname={_DB} user={_USR}")
  ```

### Why not psycopg3?

psycopg3 free-threaded support is tracked at psycopg/psycopg#1095 — open as
of June 2026, no merge date, likely targeting Python 3.15.  Do not use it.
pg8000 works today across all 24 NoGIL threads and is the right choice for the
foreseeable future.  When psycopg3 free-threaded support ships it can be
swapped in as a dialect change with no logic changes — but don't wait for it.

### Schema

The schema is defined inline in `load.py` via `CREATE TABLE` / `DROP TABLE`
statements.  There is no separate migration file — every run does a full
drop-and-rebuild.  This is intentional (design principle #4): no incremental
state, no stale rows.

Key tables (from load.py):
- `bitstreams` — one row per loaded bitstream label
- `cells` — all LUT/FF/EBR/EFB/IO primitives
- `nets` — all signal nets
- `arcs` — directed connections between nets
- `pins` — physical pin annotations from the TSV
- `efb_ports`, `ebr_ports`, `spi_registers` — known IP boundary tables

### Parallelism

`reach.py` currently hardcodes 24 threads (python3.14t, NoGIL).  The migration
must change this to use all available CPUs — `os.cpu_count()` at startup, with
the thread count set to `os.cpu_count()` (no artificial cap).  The development
machine has 32 cores; the hardcoded 24 was leaving 8 idle for no reason.

Each thread opens its own connection (pg8000 or sqlite3 — one per thread, never
shared).  SQLite's WAL mode supports concurrent readers but serialises writers —
BFS workers should accumulate results in a shared dict and let the main thread
write after all workers join (simpler and correct for both backends).

---

## Design for the new dual backend

### Driver stack

| Backend | Driver | Used by |
|---------|--------|---------|
| PostgreSQL | `pg8000` | everything — single driver, no split |
| SQLite | stdlib `sqlite3` | everything |

Use **SQLAlchemy Core** as the abstraction layer for all scripts except
reach.py.  SQLAlchemy supports pg8000 natively via `postgresql+pg8000://` and
sqlite3 via `sqlite:///path`.  reach.py keeps raw connections (pg8000.native
for postgres, sqlite3 for SQLite) because SQLAlchemy's connection pool is not
safe to share across NoGIL threads.

### Selection mechanism

Environment variable `PLURIBUS_DB_BACKEND`:
- `sqlite` (default) — DB file from `PLURIBUS_SQLITE_PATH` (default `./pluribus.db`)
- `postgres` — pg8000 via Unix socket

No config file, no CLI flag.

### `db.py` — rewrite

```python
import os, sys

BACKEND = os.environ.get("PLURIBUS_DB_BACKEND", "sqlite").lower()

_DB   = os.environ.get("PGDATABASE",       "fpga_re")
_USR  = os.environ.get("PGUSER",           os.environ.get("USER", "dan"))
_SOCK = os.environ.get("PGUNIXSOCKET",     "/run/postgresql/.s.PGSQL.5432")
_SQPATH = os.environ.get("PLURIBUS_SQLITE_PATH", "./pluribus.db")

def engine():
    """SQLAlchemy engine — for all scripts except reach.py."""
    from sqlalchemy import create_engine
    if BACKEND == "postgres":
        return create_engine(f"postgresql+pg8000://{_USR}@/{_DB}?unix_sock={_SOCK}")
    else:
        return create_engine(f"sqlite:///{_SQPATH}")

def connect_threadsafe():
    """Raw per-thread connection for reach.py NoGIL workers."""
    if BACKEND == "postgres":
        import pg8000.native
        return pg8000.native.Connection(database=_DB, user=_USR, unix_sock=_SOCK)
    else:
        import sqlite3
        conn = sqlite3.connect(_SQPATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

def die(msg):
    print(f"\nFATAL: {msg}", file=sys.stderr)
    sys.exit(1)
```

Rename all `connect()` / `connect_pg8000()` call sites:
- Non-reach scripts → `db.engine()` (SQLAlchemy)
- reach.py workers → `db.connect_threadsafe()` (raw)

### SQL compatibility

SQLAlchemy Core handles placeholders, DDL types, and `INSERT ... ON CONFLICT`
differences automatically.  Write all DDL and DML using SQLAlchemy Core
constructs (`Table`, `Column`, `insert()`, `select()`, etc.) — no raw SQL
strings except in reach.py where the raw connections are used.

For reach.py raw SQL:
- pg8000.native uses positional `$1 $2 ...` placeholders (not `%s`)
- sqlite3 uses `?` placeholders
- Write a one-liner helper in reach.py: `PH = "$1" if BACKEND == "postgres" else "?"`
  (or pass the whole paramstyle through)

### Drop-and-rebuild

For SQLite: `os.unlink(_SQPATH)` before recreating tables.  For postgres:
`DROP TABLE IF EXISTS ... CASCADE` as now.  SQLAlchemy `metadata.drop_all()` /
`metadata.create_all()` handles both.

---

## Migration steps (for the agent)

> **CRITICAL: DO NOT modify, move, or delete any files in `/mnt/2tb/git/awto-2000/`.
> All work is COPY-ONLY from awto-2000 into `/mnt/2tb/git/pluribus/`.
> awto-2000 is a live RE project; any edits there will corrupt active work.**

1. **Create repo structure** in `/mnt/2tb/git/pluribus/`:
   - Copy (do not move) `fpga/pluribus/*.py` to repo root
   - Add `README.md` (extract from `fpga/pluribus_awto-2000/pluribus.md`)
   - Add `requirements.txt`: `pg8000`, `sqlalchemy` (postgres backend also needs
     `pg8000`; SQLite backend needs nothing beyond stdlib)

2. **Rewrite `db.py`** as above — `engine()`, `connect_threadsafe()`, `die()`.
   Keep `EFB_JF` and `JF_RE` constants unchanged.

3. **Convert all non-reach scripts to SQLAlchemy Core** — define the schema
   once as `sqlalchemy.Table` objects (in a new `schema.py`), use
   `metadata.drop_all()` / `metadata.create_all()` in load.py, and use
   `conn.execute(insert(table).values(...))` everywhere psycopg2 executemany
   was used.

4. **Update reach.py** — replace `connect_pg8000()` with `connect_threadsafe()`,
   add SQLite WAL path, accumulate BFS results in shared dict, main thread
   writes after join.

5. **Write smoke test** `tests/test_sqlite.py` — load a minimal fixture,
   assert row counts, run with `PLURIBUS_DB_BACKEND=sqlite`.

6. **Update CLAUDE.md / README** with new env vars and usage.

7. **First task after the new system works: parametric trellis lifter + ECP5.**
   The lifter should be parametric — `lifters/trellis_lift.py` takes a `family`
   argument (`"MachXO2"`, `"ECP5"`, eventually `"Nexus"`) and a per-family
   config dict covering the differences:
   - Primitive name sets (`FACADE_FF`/`FACADE_IO` for MachXO2 vs
     `TRELLIS_FF`/`TRELLIS_IO` for ECP5)
   - EFB/EBR port names
   - Tile naming conventions
   pytrellis already has a unified API across families — `family` is just a
   parameter to `pytrellis.load_database()` and the chip constructor.  The walk
   (cells → arcs → IO classification) is identical structure in both.
   `machxo2_lift.py` and `ecp5_lift.py` become thin wrappers:
   `trellis_lift.lift(path, family="ECP5", ...)`.

   First real ECP5 target: **Cynthion** (Great Scott Gadgets).  See
   `fpga/pluribus_cynthion/` in awto-2000 for any prior groundwork.  Goal: load
   a Cynthion bitstream through the parametric lifter and produce the same
   generic cells/nets/arcs schema that MachXO2 produces.

---

## What NOT to change

- The always-rebuild design (no migrations, no incremental state).
- The `die()` / hard-exit-on-any-error discipline.
- The NoGIL parallel BFS — keep `python3.14t` and 24 threads.
- The TSV annotation file format and parse logic in `load.py`.
- The project-specific layer (`fpga/pluribus_awto-2000/`) — it stays in
  `awto-2000` and imports from the now-separate `pluribus` package.

---

## Testing the PostgreSQL path still works

```bash
cd /mnt/2tb/git/awto-2000
PLURIBUS_DB_BACKEND=postgres ./scripts/rebuild
```
All stage counts must match the pre-migration baseline.

---

## Constraints / gotchas

- `pg8000.native.Connection` uses `conn.run(sql, param=val)` not `cur.execute()`.
  Already handled in current reach.py — don't break it.
- pg8000 positional placeholders are `$1`, `$2` ... not `%s`.
- SQLite `INTEGER PRIMARY KEY` is implicitly ROWID — use `lastrowid` for the
  new row ID after INSERT (SQLAlchemy handles this transparently via `inserted_primary_key`).
- `PRAGMA journal_mode=WAL` must be the first statement on a fresh sqlite3
  connection.
- `machxo2_lift` (imported by load.py) lives in `fpga/scripts/` in awto-2000
  but **should be copied into `pluribus/lifters/machxo2_lift.py`** — it is the
  first of a family of device lifters (`ecp5_lift.py`, `ice40_lift.py`,
  `nexus_lift.py`, etc.) that each translate a device-family bitstream into the
  generic netlist representation pluribus ingests.  The engine never cares which
  family — it sees cells, nets, arcs.  The awto-2000 project-specific layer
  selects the lifter; the lifters themselves belong in the engine repo.
