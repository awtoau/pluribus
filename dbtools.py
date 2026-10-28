"""Multi-database helpers (one DB file per family / product / project, all from schema.py).

db.py keeps exactly three public functions; cross-DB work lives here.

  dbtools.kept()                       -> {alias: path} of databases/**/*.db
  dbtools.open_ro(path)                -> read-only sqlite3 connection (schema.init never runs)
  dbtools.attach(conn, alias, path)    -> ATTACH a second file to a sqlite3 connection
  dbtools.open_many(paths)             -> one connection, 'main' + each alias attached (read-only)
  dbtools.union(conn, sql, aliases)    -> run `sql` per alias (table names prefixed) and UNION ALL

Cross-family questions are an explicit union over attached files, never a foreign key across
files. Layout convention: databases/<family>/<name>.db (databases/README.md).
"""
import contextlib
import os
import re
import sqlite3

import db

REPO = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(REPO, "databases")
_ALIAS_RE = re.compile(r"[^A-Za-z0-9_]")


# Default file per family under databases/<family>/ (databases/README.md). PLURIBUS_SQLITE_PATH, when set,
# always wins: a tool that reads another family's rows must be pointed at that file explicitly.
FAMILY_DB = {"cycloneiv": "cycloneiv/gx150.db", "cyclonev": "cyclonev/provenance.db", "machxo2": "machxo2/provenance.db",
             "ecp5": "ecp5/provenance.db", "gowin": "gowin/provenance.db", "anlogic": "anlogic/provenance.db"}


def family_db(family):
    """Path of the family's database: $PLURIBUS_SQLITE_PATH if set, else databases/<family>/<default>."""
    env = os.environ.get("PLURIBUS_SQLITE_PATH")
    if env:
        return env
    if family not in FAMILY_DB:
        db.die(f"no default database for family {family!r} (dbtools.FAMILY_DB)")
    return os.path.join(DB_DIR, FAMILY_DB[family])


def alias_of(path):
    """databases/cycloneiv/gx150.db -> cycloneiv_gx150; a bare file -> its stem."""
    rel = os.path.relpath(os.path.abspath(path), DB_DIR)
    stem = rel[:-3] if rel.endswith(".db") else rel
    if stem.startswith(".."):
        stem = os.path.splitext(os.path.basename(path))[0]
    return _ALIAS_RE.sub("_", stem)


def kept():
    """Every kept DB under databases/ (family subdirs and legacy flat files)."""
    out = {}
    if not os.path.isdir(DB_DIR):
        return out
    for root, _dirs, files in os.walk(DB_DIR):
        for f in sorted(files):
            if f.endswith(".db"):
                p = os.path.join(root, f)
                out[alias_of(p)] = p
    return out


def open_ro(path):
    if db.BACKEND != "sqlite":
        db.die("dbtools.open_ro is SQLite-only; use a separate PGDATABASE per family on PostgreSQL")
    if not os.path.exists(path):
        db.die(f"no database at {path}")
    return sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)


def attach(conn, alias, path):
    if _ALIAS_RE.search(alias):
        db.die(f"bad alias {alias!r}")
    if not os.path.exists(path):
        db.die(f"no database at {path}")
    conn.execute(f"ATTACH DATABASE ? AS {alias}", (f"file:{os.path.abspath(path)}?mode=ro",))
    return alias


def open_many(paths):
    """-> (conn, aliases): one read-only connection with every path attached under its alias."""
    if db.BACKEND != "sqlite":
        db.die("dbtools.open_many is SQLite-only")
    conn = sqlite3.connect(":memory:")
    aliases = []
    for p in paths:
        a = alias_of(p)
        conn.execute(f"ATTACH DATABASE ? AS {a}", (f"file:{os.path.abspath(p)}?mode=ro",))
        aliases.append(a)
    return conn, aliases


def has_table(conn, alias, table):
    r = conn.execute(f"SELECT name FROM {alias}.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return r is not None


def union(conn, sql, aliases, tables):
    """Run `sql` once per alias with every name in `tables` prefixed `<alias>.`; UNION ALL the rows,
    each prefixed by the alias. Aliases lacking any of the tables are skipped."""
    parts = []
    for a in aliases:
        if not all(has_table(conn, a, t) for t in tables):
            continue
        q = sql
        for t in tables:
            q = re.sub(rf"\b{t}\b", f"{a}.{t}", q)
        parts.append(f"SELECT '{a}' AS db, * FROM ({q})")
    if not parts:
        return []
    return conn.execute(" UNION ALL ".join(parts)).fetchall()


# ── SQLite bulk-write helpers for the derived-table pipeline stages (#144) ───────────────────
# Used after the stage's DELETE (always-rebuild): plain INSERT, no per-row upsert; one transaction;
# synchronous=OFF scoped to the connection and restored; declared indexes dropped and recreated
# around the load when PLURIBUS_BULK_DROP_INDEXES != "0". Measured: scripts/bench_reach_sql.py.

@contextlib.contextmanager
def fast_writes(conn):
    """sqlite3 connection: synchronous=OFF for the block (derived tables only), restored after."""
    old = conn.execute("PRAGMA synchronous").fetchone()[0]
    conn.execute("PRAGMA synchronous=OFF")
    try:
        yield
        conn.commit()
    finally:
        conn.execute(f"PRAGMA synchronous={int(old)}")


def bulk_insert(conn, table, cols, rows, chunk=5000):
    """Plain INSERT in multi-row VALUES statements (chunk x len(cols) <= 32766 bound variables)."""
    cols = tuple(cols)
    head = f"INSERT INTO {table} ({','.join(cols)}) VALUES "
    one = "(" + ",".join("?" * len(cols)) + ")"
    n = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i:i + chunk]
        conn.execute(head + ",".join([one] * len(batch)), [v for r in batch for v in r])
        n += len(batch)
    return n


@contextlib.contextmanager
def without_indexes(conn, table):
    """Drop the table's declared (non-unique, non-auto) indexes for a bulk load; recreate on exit."""
    if os.environ.get("PLURIBUS_BULK_DROP_INDEXES", "1") == "0":
        yield
        return
    names = [r[1] for r in conn.execute(f"PRAGMA index_list({table})")
             if not r[1].startswith("sqlite_autoindex") and not r[2]]
    defs = {n: conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (n,)).fetchone()[0] for n in names}
    for n in defs:
        conn.execute(f"DROP INDEX {n}")
    try:
        yield
    finally:
        for sql in defs.values():
            conn.execute(sql)


# Example: claims by tier across every kept database.
CLAIMS_BY_TIER_SQL = ("SELECT family, device, tier, status, COUNT(*) AS n, SUM(n_objects) AS objects "
                      "FROM claims GROUP BY family, device, tier, status")


def claims_by_tier_all(paths=None):
    paths = paths or list(kept().values())
    conn, aliases = open_many(paths)
    try:
        return union(conn, CLAIMS_BY_TIER_SQL, aliases, ["claims"])
    finally:
        conn.close()
