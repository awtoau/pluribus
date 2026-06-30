"""Pluribus — database helpers (dual SQLite / PostgreSQL backend).

Backend selected via PLURIBUS_DB_BACKEND env var (default: sqlite).

Public API
----------
  engine()              — SQLAlchemy engine (cached singleton)
  connect()             — psycopg2-compatible shim for non-reach scripts
  connect_threadsafe()  — raw per-thread connection for reach.py NoGIL workers
  execute_values(cur, sql, rows)  — drop-in for psycopg2.extras.execute_values
  die(msg)              — print FATAL and sys.exit(1)
  EFB_JF, JF_RE         — shared constants
"""

import os
import re
import sys

# ── Backend selection ─────────────────────────────────────────────────────────

BACKEND = os.environ.get("PLURIBUS_DB_BACKEND", "sqlite").lower()

_DB     = os.environ.get("PGDATABASE",           "fpga_re")
_USR    = os.environ.get("PGUSER",               os.environ.get("USER", "dan"))
_SOCK   = os.environ.get("PGUNIXSOCKET",          "/run/postgresql/.s.PGSQL.5432")
_SQPATH = os.environ.get("PLURIBUS_SQLITE_PATH",  "./pluribus.db")

# ── SQLAlchemy engine (cached) ────────────────────────────────────────────────

_engine = None


def engine():
    """Return (and cache) the SQLAlchemy engine for the active backend."""
    global _engine
    if _engine is not None:
        return _engine
    from sqlalchemy import create_engine, event, text
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
    return _engine


# ── Raw per-thread connection (reach.py NoGIL workers) ───────────────────────

def connect_threadsafe():
    """Per-thread raw connection for python3.14t NoGIL reach.py workers.

    PostgreSQL: pg8000.native.Connection — pure Python, GIL never re-enabled.
    SQLite:     sqlite3.Connection with WAL mode — concurrent readers are fine;
                BFS workers accumulate results and the main thread writes after join.
    """
    if BACKEND == "postgres":
        import pg8000.native
        return pg8000.native.Connection(database=_DB, user=_USR, unix_sock=_SOCK)
    else:
        import sqlite3
        conn = sqlite3.connect(_SQPATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


# ── psycopg2-compatible shim (all non-reach scripts) ─────────────────────────

_PH_RE = re.compile(r'%s')


def _pg_to_sa(sql):
    """Convert positional %s placeholders to SQLAlchemy :p0, :p1, … style."""
    idx = [0]
    def _sub(_m):
        n = idx[0]; idx[0] += 1
        return f":p{n}"
    return _PH_RE.sub(_sub, sql)


class _Cursor:
    """Thin cursor shim over a SQLAlchemy connection."""
    def __init__(self, conn):
        self._conn    = conn
        self._result  = None
        self.rowcount = 0

    def execute(self, sql, params=()):
        from sqlalchemy import text as _text
        sa_sql = _pg_to_sa(sql)
        pmap   = {f"p{i}": v for i, v in enumerate(params)}
        self._result  = self._conn.execute(_text(sa_sql), pmap)
        self.rowcount = self._result.rowcount

    def executemany(self, sql, params_seq):
        from sqlalchemy import text as _text
        sa_sql    = _pg_to_sa(sql)
        dict_rows = [{f"p{i}": v for i, v in enumerate(row)} for row in params_seq]
        if dict_rows:
            self._result  = self._conn.execute(_text(sa_sql), dict_rows)
            self.rowcount = self._result.rowcount
        else:
            self.rowcount = 0

    def fetchall(self):
        return list(self._result) if self._result else []

    def fetchone(self):
        return self._result.fetchone() if self._result else None

    def close(self):
        pass


class _Conn:
    """psycopg2-compatible connection shim backed by SQLAlchemy."""
    def __init__(self):
        self._conn = engine().connect()

    def cursor(self):
        return _Cursor(self._conn)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def connect():
    """Return a psycopg2-compatible connection backed by SQLAlchemy.

    All non-reach scripts use this.  The cursor, execute, fetchall, commit,
    and close interface is preserved so existing code needs minimal changes.
    """
    return _Conn()


# ── execute_values replacement ────────────────────────────────────────────────

def execute_values(cur_or_conn, sql, rows, page_size=2000):
    """Drop-in replacement for psycopg2.extras.execute_values.

    Replaces the %s placeholder in the VALUES clause with column placeholders
    and executes as a bulk insert via SQLAlchemy.
    """
    if not rows:
        return
    n    = len(rows[0])
    ph   = "(" + ",".join(f":p{i}" for i in range(n)) + ")"
    stmt = sql.replace("%s", ph, 1)   # replace only the VALUES %s
    from sqlalchemy import text as _text
    dict_rows = [{f"p{i}": v for i, v in enumerate(row)} for row in rows]
    sa_conn = (cur_or_conn._conn
               if isinstance(cur_or_conn, _Cursor)
               else cur_or_conn._conn)
    sa_conn.execute(_text(stmt), dict_rows)


# ── Shared utilities ──────────────────────────────────────────────────────────

def die(msg):
    """Print FATAL message and exit 1. Never returns."""
    print(f"\nFATAL: {msg}", file=sys.stderr)
    sys.exit(1)


EFB_JF = {0: "JTCK", 1: "JTDI", 2: "JUPDATE", 3: "JRSTN",
           4: "JSHIFTDR", 5: "JTDO", 6: "JF6", 7: "JF7"}

JF_RE = re.compile(r'^JF(\d)$')
