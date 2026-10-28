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
import os
import re
import sqlite3

import db

REPO = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(REPO, "databases")
_ALIAS_RE = re.compile(r"[^A-Za-z0-9_]")


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
