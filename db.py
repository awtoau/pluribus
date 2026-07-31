"""Pluribus — database helpers (dual SQLite / PostgreSQL backend).

Backend selected via PLURIBUS_DB_BACKEND env var (default: sqlite).

Public API
----------
  engine()             — SQLAlchemy engine (cached singleton)
  connect_threadsafe() — raw per-thread connection for reach.py NoGIL workers
  die(msg)             — print FATAL and sys.exit(1)
  BACKEND              — "sqlite" or "postgres"
  EFB_JF, JF_RE        — shared constants
"""

import os
import re
import sys

BACKEND = os.environ.get("PLURIBUS_DB_BACKEND", "sqlite").lower()

_DB     = os.environ.get("PGDATABASE",          "fpga_re")
_USR    = os.environ.get("PGUSER",              os.environ.get("USER", "dan"))
_SOCK   = os.environ.get("PGUNIXSOCKET",         "/run/postgresql/.s.PGSQL.5432")
_SQPATH = os.environ.get("PLURIBUS_SQLITE_PATH", "./pluribus.db")

_engine = None


def engine():
    """Return (and cache) the SQLAlchemy engine for the active backend."""
    global _engine
    if _engine is not None:
        return _engine
    from sqlalchemy import create_engine, event
    if BACKEND == "postgres":
        _engine = create_engine(
            f"postgresql+pg8000://{_USR}@/{_DB}?unix_sock={_SOCK}",
            pool_pre_ping=True,
        )
    else:
        _engine = create_engine(
            f"sqlite:///{_SQPATH}",
            connect_args={"check_same_thread": False},
        )
        @event.listens_for(_engine, "connect")
        def _on_connect(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA synchronous=NORMAL")
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            dbapi_conn.execute("PRAGMA busy_timeout=30000")
    return _engine


def connect_threadsafe():
    """Per-thread raw connection for python3.14t NoGIL reach.py workers.

    PostgreSQL: pg8000.native — pure Python, GIL never re-enabled.
    SQLite: sqlite3 with WAL — BFS workers read only; main thread writes after join.
    """
    if BACKEND == "postgres":
        import pg8000.native
        return pg8000.native.Connection(database=_DB, user=_USR, unix_sock=_SOCK)
    else:
        import sqlite3
        conn = sqlite3.connect(_SQPATH, check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn


def die(msg):
    print(f"\nFATAL: {msg}", file=sys.stderr)
    sys.exit(1)


# The JF0..7 fabric bus.  These names used to be a GUESS -- JTCK/JTDI/JUPDATE/
# JRSTN/JSHIFTDR/JTDO, i.e. JTAG signals -- made when there was no fuzzer-derived
# EFB evidence at all (docs/fuzzing-coverage.md), and flagged in
# docs/diamond-re-oracle.md as "the anti-pattern".
#
# The device database says what these wires actually carry, and it is not JTAG:
#     device-db/MachXO2/tiledata/CIB_CFG0/bits.db
#     .fixed_conn E2_JF0 JWBDATO0_EFB   ...   .fixed_conn E2_JF7 JWBDATO7_EFB
# an eight-bit Wishbone data-out bus, JF<n> -> JWBDATO<n>, one for one.
#
# Keeping the guess did real damage: load.py labelled every JF net from BOTH
# sources -- JWBDATO<n> from the database's fixed_conn (evidence) and a JTAG name
# from this table (invention) -- so each of the eight nets ended up with two
# output drivers.  That is the 7 conflicting drivers that failed the yosys gate
# on the only design here with an active EFB, while EFB-less designs passed.
#
# Now derived from the database rather than asserted.  Kept as a name map only
# because load.py's JF_RE path wants a port name per index; the mapping is
# mechanical and matches the fixed_conn table exactly.
EFB_JF = {n: f"JWBDATO{n}" for n in range(8)}

JF_RE = re.compile(r'^JF(\d)$')
