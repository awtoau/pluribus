# Pluribus — dual-backend migration summary

## Work done

**Starting point:** PostgreSQL-only FPGA RE analysis engine copied from awto-2000.
All scripts used psycopg2 directly, schema was raw SQL DDL, lifter was a bare module.

### Commits

| Commit | What |
|---|---|
| `b40068a` | Repo structure: source files, `lifters/` package, README, requirements.txt |
| `c6ee008` | `db.py` — dual-backend engine + SQLAlchemy Core; `schema.py` — all ~26 tables, cross-dialect JSON for `TEXT[]`/`JSONB` |
| `cbdc2ba` | `load.py`, `reach2/3/4.py` converted — psycopg2 removed |
| `489e86f` | `reach.py` — `connect_threadsafe()` for NoGIL workers, SQLite bulk-insert path, `os.cpu_count()` replacing hardcoded 24 |
| `bb1c0dc` | `tests/test_sqlite.py` — 8 smoke tests; `BigInteger` PK → `Integer` (SQLite only autoincrements `INTEGER PRIMARY KEY`) |
| `0a30393` | `CLAUDE.md` |
| `5b2020f` | Path/import fixes: `machxo2_lift` moved into `lifters/` package (missed in 3 files), `reset_db()` rewritten for dual-backend |
| `a1bf23c` | Tests rewritten to use `engine().begin()` + SQLAlchemy Core (psycopg2 shim was removed in a prior session; tests were broken) |
| `633f98f` | `load.py`: set `loaded_at` on bitstream upsert; remove dead duplicate SQLite branch |
| `0b3658f` | `reach2.py` dominator query: 370s → 0.16s (see below) |

### How the backend abstraction works

- `PLURIBUS_DB_BACKEND=sqlite` (default) — SQLAlchemy + sqlite3, WAL mode, no server
- `PLURIBUS_DB_BACKEND=postgres` — SQLAlchemy + pg8000 (pure Python, NoGIL-safe)
- All scripts use `engine()` + SQLAlchemy Core with `text()` for complex SQL
- `reach.py` uses `db.connect_threadsafe()` for raw per-thread connections (NoGIL workers can't share SQLAlchemy pool)
- SQL divergences handled explicitly: `LEAST()` → `CASE WHEN` (SQLite), `ARRAY[...]` → `json_array(...)` (SQLite)

### Full pipeline verified (V07 bitstream, LCMXO2-1200)

| Stage | Result | Time |
|---|---|---|
| `load.py` | 1105 FFs, 1138 LUTs, 3076 nets, 12808 arcs | 1.1s |
| `reach.py` | 252,218 reachability pairs | 0.8s |
| `reach2.py` | 115,370 cone entries, 12,472 dominators | 4s |
| `reach3.py` | LUT expansion, clock crossings, cone hashes | 0.4s |
| `reach4.py` | 1200/3104 nets named (38.7%) | 0.2s |
| `report.py` | Full report renders correctly | — |

### Dominator query fix (`reach2.py`)

The original SQLite dominator query did a triple self-join on `reachability`
(252k rows). SQLite's planner couldn't push the CTE-derived `pad_net` value
into an index scan, falling back to a full table scan for each (ff, pad)
combination — O(n²), ~370s.

Rewritten to use `ff_cones` (input cone per FF, 26k rows) and `pad_map`
(18 rows) with a covering-index lookup on `reachability(bitstream, src, dst)`.
Result: identical dominator set, 0.16s.

---

## Issue #9 — parametric lifter + ECP5

### The problem

`lifters/machxo2_lift.py` is MachXO2-specific. To support ECP5 you can't just copy it —
the two families differ only in primitive names and a few tile conventions; the walk
(cells → arcs → IO classification) is identical because pytrellis already exposes a
unified API across families.

### What needs doing

1. **Read `machxo2_lift.py` carefully** and identify exactly what is family-specific
   vs generic. Expected to be only: primitive cell names (`FACADE_FF`, `FACADE_IO`,
   `FACADE_SLICE`), EFB/EBR port name sets, and possibly tile naming patterns.
   Everything else (DSU union-find, net recovery, arc walking) should be identical.

2. **Write `lifters/trellis_lift.py`** — parametric lifter that takes `family` as an
   argument and a per-family config dict. `pytrellis.load_database(dbroot, family)` and
   the chip constructor both accept `family` directly.

3. **Thin wrappers:** `machxo2_lift.py` and `ecp5_lift.py` become one-liners calling
   `trellis_lift.lift(path, family="MachXO2"` / `family="ECP5")`.

4. **First ECP5 target: Cynthion** (Great Scott Gadgets). Check `fpga/pluribus_cynthion/`
   in awto-2000 (read-only) for any prior groundwork — a Cynthion bitstream and
   possibly a pins.tsv.

### Before starting

Read `machxo2_lift.py` top to bottom and make a list of every family-specific
constant/name. That list becomes the per-family config dict schema.
