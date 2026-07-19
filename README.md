# Pluribus — FPGA Reverse-Engineering Static Analysis Engine

Pluribus turns an FPGA **bitstream** into a **full structural netlist** and stores
it in a **relational database you query to answer reverse-engineering questions** —
*what drives this net? which clock domain is this in? what arms this capture engine?
which pad is this signal on?* It also emits recovered structural Verilog and
human-readable RE reports.

It is **backend-agnostic** (multiple FPGA vendors, one schema) and runs entirely
on **free-threaded Python 3.15t** — pure Python, no compiled `.so`.

```
        bitstream.bin
            │  decode (per-family native decoder)
            ▼
        .config  ──lift──▶  generic cells / nets / arcs / ffs / luts / bram / pads
            │                         │
            │                    load into relational DB
            ▼                         ▼
     recovered .v   ◀──────  reachability · clock domains · cones · patterns · names
     (structural)            │
                             ▼
                   query the DB for RE answers  (api.Netlist + SQL + reports)
```

---

## Quick start

```bash
pip install -r requirements.txt

# One command: bitstream → queryable netlist + report + recovered Verilog.
python3.15t scripts/run_pipeline.py --board boards/<name> --label <LABEL>
```

Deliverables land in `out/<LABEL>.v` (recovered Verilog) and
`out/<LABEL>-chains.txt`. See **[docs/pipeline.md](docs/pipeline.md)** for stages,
board setup, and every flag.

---

## What it does — the full pipeline

`scripts/run_pipeline.py` is the canonical entry point; it chains every stage under
one free-threaded interpreter, board-driven. The stages, in order:

| Stage | Script | Produces |
|---|---|---|
| **unpack** | `scripts/{trellis,gowin,anlogic}_unpack.py` | bitstream `.bin` → `.config` (per-family **native** decoder — lossless) |
| **iomap** | `scripts/fpga_iomap.py` | `.config` → pin ↔ site map |
| **load** | `load.py` (+ `lifters/<family>_lift.py`) | `.config` → DB netlist: `nets` / `ffs` / `luts` / `arcs` / `bram` / `pad_map` |
| **annotate** | `annotate.py` | overlay board knowledge (pin names, register maps, open questions) |
| **reach** | `reach.py` | all-net forward reachability — NoGIL-parallel BFS |
| **reach2/3/4** | `reach2.py` … | reverse reach, logic cones, symbolic LUTs, multi-pass auto-naming |
| **auto_name** | `auto_name.py` | net names inferred from LUT-INIT truth tables + expression patterns |
| **patterns** | `patterns.py` | structural-pattern table (stuck/orphan pads, const-FFs, shift regs…) |
| **report** | `report.py` | human RE report — netlist, clock architecture, boundary, BRAM, patterns |
| **report_resources** | `report_resources.py` | resource census + by-peripheral pin map, liveness, unknown-bit edges |
| **chains** | `chains.py` | signal-chain report → `out/<label>-chains.txt` |
| **verilog** | `verilog.py` | recovered structural Verilog → `out/<label>.v` |
| **verify** | `scripts/check_verilog.py` | lint (0 comb-loops / 0 conflicting drivers) + regression LEC |

Then you **query** the result — `api.Netlist(label)` or direct SQL over the schema.

---

## Supported FPGA families

One generic `cells` / `nets` / `arcs` schema; each family has a lifter that maps its
bitstream into it.

| Family | Decoder basis | Lifter | Status |
|---|---|---|---|
| **Lattice MachXO2** | prjtrellis (native port) | `lifters/machxo2_lift.py` | production — fabric + routing + BRAM/EFB, verified vs vendor round-trip |
| **Gowin GW1N** | Project Apicula chipdb | `lifters/gowin_lift.py` | production — decode validated byte-faithful vs the vendor toolchain |
| **Anlogic EG4** | prjtang (arch-DB decode) | `lifters/anlogic_lift.py` | fabric + LUTs land; routing/mux decode is WIP |
| Lattice ECP5 | prjtrellis | *(planned)* | via the parametric `lifters/trellis_lift.py` |

---

## Why it's built this way

The three design bets that shape the whole engine:

### 1. A relational DB — because RE *is* question-answering
Recovering a `.v` file is only half the job. The real work is *interrogating* the
design: "trace every driver of this readback net", "which FFs share this clock
spine", "what gates this BRAM's write-enable", "cross-reference pads against the
register map". A flat netlist forces you to grep and hand-trace. A **normalized,
indexed netlist in SQL** lets you answer these with joins and recursive
reachability — and the answers are reproducible, not one-off manual traces. That is
the core product: not the Verilog, the *queryable model*. Precomputed
reachability/cone tables mean a fan-out or "what-drives-what" query is a lookup, not
a graph walk.

### 2. Free-threaded (NoGIL) Python — because the analysis is massively parallel
Reachability over a real design is millions of nets and arcs, and it's
embarrassingly parallel (independent per-net BFS). Under the classic GIL you'd pay
either GIL contention (threads) or serialization + memory blowup (processes).
Pluribus runs on **Python 3.15t (free-threaded)**: true-parallel worker threads over
**shared read-only** routing structures (immortalized so refcount churn doesn't
serialize them — see `ft_immortal.py`), one interpreter for the whole pipeline. It
stays pure Python (no pytrellis `.so`) precisely so nothing re-enables the GIL; the
native decoder + routing graph are validated byte-identical to the compiled path.

### 3. Always-rebuild — because RE is iterative
You refine the lifter or the decode and re-run *constantly*. So every run **drops
and recreates all rows** for the label — no incremental state, no stale rows, no
schema migrations. A run always reflects the current code exactly; a fast full
rebuild *is* the migration. Derived artifacts (DBs, reports, recovered `.v`) have no
legacy: regenerate, don't patch.

### 4. Verified output — because a plausible netlist isn't enough
A recovered netlist that *looks* right can be subtly wrong (bit-order, primitive
mapping, an undriven net). So recovery is checked against ground truth:
`check_verilog.py` (structural lint), round-trip LEC harnesses
(`scripts/machxo2_roundtrip.py`, `scripts/gowin_lec.py`), and vendor-flow
differential fuzzing (`scripts/gowin_fuzz.py`) that confirms the decode matches what
the real vendor toolchain produces.

---

## Querying for RE answers

```python
from api import Netlist
nl = Netlist("MY_LABEL")
nl.net_for_pad("SPI_CS")   # which fabric net a pad drives
nl.pad_for_net(net)        # which pad(s) a net reaches
nl.reachable(net)          # everything a net reaches (precomputed reachability)
nl.spi_regs()              # decoded SPI register map
nl.shift_registers()       # recovered shift-register chains
```

Or go straight to SQL — the schema (`schema.py`) is stable and documented: `nets`,
`ffs`, `luts`, `arcs`, `reachability`, `clock_domains`, `clock_domain_summary`,
`ebr_ports`, `pad_map`, `patterns`, `spi_registers`, …

---

## Options

| Variable | Default | Purpose |
|---|---|---|
| `PLURIBUS_DB_BACKEND` | `sqlite` | `sqlite` (no server) or `postgres` (CI / shared) |
| `PLURIBUS_SQLITE_PATH` | `./pluribus.db` | SQLite file path |
| `PLURIBUS_PYTHON` | `python3.15t` | interpreter used for chained stages |
| `PGDATABASE` / `PGUSER` / `PGUNIXSOCKET` | `fpga_re` / `$USER` / … | PostgreSQL connection |

Common pipeline flags: `--all` (every bitstream a board declares), `--skip-load`
(re-run analysis on an already-loaded label), `--workers N` (BFS parallelism),
`--no-verilog` / `--no-verify`, `--top <module>`. Full list in
[docs/pipeline.md](docs/pipeline.md).

---

## Design rules (do not change)

- **Always-rebuild** per bitstream — drop + recreate, no incremental state.
- **Fail fast** — any unexpected condition calls `db.die()` / `sys.exit(1)`; never a
  soft warning that continues.
- **`schema.py` owns all DDL** — add tables there and call `schema.init()`; never
  `CREATE TABLE` in a stage script.
- **pg8000 only** for PostgreSQL (pure Python, NoGIL-safe). psycopg2/psycopg3 are
  not used ([psycopg/psycopg#1095](https://github.com/psycopg/psycopg/issues/1095)).

---

## Repository layout

```
run_pipeline.py driver → scripts/            stage scripts (unpack, iomap, verify, LEC, fuzz)
pipeline stages         → *.py at root       load, reach{,2,3,4}, auto_name, patterns,
                                             report, chains, verilog, annotate, api
family lifters          → lifters/           machxo2 / gowin / anlogic / trellis (parametric)
board configs           → boards/<name>/     board.toml + pins.tsv (points at bitstreams)
schema + DB access      → schema.py, db.py, clocks.py, ft_immortal.py
docs                    → docs/               pipeline, per-topic RE notes
```

Board-specific data (pin TSVs, bitstream paths) lives in each board dir or an
external project repo; this repo is the generic engine.
