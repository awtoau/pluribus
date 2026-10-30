#!/usr/bin/env python3
"""Migrate a SQLite family DB to the current schema.py (lossless). Dry-run by default.

- Compares every declared table: columns, foreign keys, indexes.
- Legacy renames (copy rows then drop old): postfit_builds -> corpus_builds, patterns -> netlist_patterns.
- Tables whose columns/FKs differ: copy-then-swap (rename old, create declared, copy common columns, drop old).
- Missing indexes are created. Extra tables / indexes are reported, never dropped (legacy names above excepted).
- --apply: backup (sqlite backup API + integrity_check) -> one transaction, foreign_keys=OFF -> foreign_key_check -> row counts.
- Log: ./tmp/logs/migrate_family_db.log
Usage: PLURIBUS_SQLITE_PATH=databases/cycloneiv/gx150.db scripts/migrate_family_db.py [--apply]
Issue: #170
"""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("PLURIBUS_REPO") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(REPO))
import schema  # noqa: E402

LEGACY = {"postfit_builds": "corpus_builds", "patterns": "netlist_patterns"}
LOG = REPO / "tmp" / "logs" / "migrate_family_db.log"


def log(msg):
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def tables(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}


def cols(con, t):
    return [r[1] for r in con.execute(f'pragma table_info("{t}")')]


def fks(con, t):
    groups = {}
    for r in con.execute(f'pragma foreign_key_list("{t}")'):
        groups.setdefault(r[0], []).append(r)
    return {(tuple(x[3] for x in sorted(g, key=lambda x: x[1])), g[0][2],
             tuple(x[4] for x in sorted(g, key=lambda x: x[1]))) for g in groups.values()}


def declared_fks(tbl):
    return {(tuple(e.parent.name for e in fk.elements), fk.elements[0].column.table.name,
             tuple(e.column.name for e in fk.elements)) for fk in tbl.foreign_key_constraints}


def plan(con):
    have = tables(con)
    p = {"legacy": [], "recreate": [], "indexes": [], "extra": []}
    for old, new in LEGACY.items():
        if old in have:
            p["legacy"].append((old, new))
    for t in schema.metadata.sorted_tables:
        if t.name not in have:
            continue  # create_all makes it
        why = []
        missing = set(c.name for c in t.columns) - set(cols(con, t.name))
        if missing:
            why.append(f"missing cols {sorted(missing)}")
        if fks(con, t.name) != declared_fks(t):
            why.append(f"fk live={sorted(fks(con, t.name))} declared={sorted(declared_fks(t))}")
        if why:
            p["recreate"].append((t.name, "; ".join(why)))
        idx = {r[1] for r in con.execute(f'pragma index_list("{t.name}")')}
        p["indexes"] += [i.name for i in t.indexes if i.name not in idx]
    declared = {t.name for t in schema.metadata.sorted_tables}
    p["extra"] = sorted(have - declared - set(LEGACY))
    return p


def copy_rows(con, src, dst):
    common = [c for c in cols(con, dst) if c in cols(con, src)]
    cl = ", ".join(f'"{c}"' for c in common)
    con.execute(f'insert into "{dst}" ({cl}) select {cl} from "{src}"')


def apply(con, p):
    md = schema.metadata
    con.execute("pragma foreign_keys=OFF")
    con.execute("pragma legacy_alter_table=ON")  # rename must not rewrite other tables' FKs
    con.execute("begin")
    try:
        have = tables(con)
        # create declared tables that are absent (incl. legacy targets)
        for t in md.sorted_tables:
            if t.name not in have:
                create_table(con, t)
        for old, new in p["legacy"]:
            n_new = con.execute(f'select count(*) from "{new}"').fetchone()[0]
            n_old = con.execute(f'select count(*) from "{old}"').fetchone()[0]
            if n_new and n_old:
                raise SystemExit(f"both {old} ({n_old}) and {new} ({n_new}) populated: refusing")
            if n_old:
                copy_rows(con, old, new)
                assert con.execute(f'select count(*) from "{new}"').fetchone()[0] == n_old
                log(f"legacy {old} -> {new}: {n_old} rows")
        for name, _ in p["recreate"]:
            t = md.tables[name]
            n = con.execute(f'select count(*) from "{name}"').fetchone()[0]
            for r in con.execute(f'pragma index_list("{name}")').fetchall():
                if r[3] == "c":
                    con.execute(f'drop index "{r[1]}"')
            con.execute(f'alter table "{name}" rename to "_old_{name}"')
            create_table(con, t)
            copy_rows(con, f"_old_{name}", name)
            assert con.execute(f'select count(*) from "{name}"').fetchone()[0] == n, name
            con.execute(f'drop table "_old_{name}"')
            log(f"recreated {name}: {n} rows")
        have = tables(con)
        for t in md.sorted_tables:
            idx = {r[1] for r in con.execute(f'pragma index_list("{t.name}")')}
            for i in t.indexes:
                if i.name not in idx:
                    create_index(con, i)
                    log(f"index {i.name}")
        for old, _ in p["legacy"]:
            con.execute(f'drop table "{old}"')
        bad = con.execute("pragma foreign_key_check").fetchall()
        if bad:
            raise SystemExit(f"foreign_key_check: {len(bad)} violations, first {bad[:3]}")
        con.execute("commit")
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("pragma legacy_alter_table=OFF")


def _ddl(con, ddl):
    from sqlalchemy.dialects import sqlite
    con.execute(str(ddl.compile(dialect=sqlite.dialect())))


def create_table(con, tbl):
    from sqlalchemy.schema import CreateTable
    _ddl(con, CreateTable(tbl))
    for i in tbl.indexes:
        create_index(con, i)


def create_index(con, idx):
    from sqlalchemy.schema import CreateIndex
    _ddl(con, CreateIndex(idx))


def backup(path):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = Path(path).parent / "backup" / f"{Path(path).stem}-{ts}-premigrate.db"
    dst.parent.mkdir(exist_ok=True)
    s, d = sqlite3.connect(path), sqlite3.connect(dst)
    s.backup(d)
    ok = d.execute("pragma integrity_check").fetchone()[0]
    assert ok == "ok", ok
    for t in tables(s):
        assert s.execute(f'select count(*) from "{t}"').fetchone() == d.execute(f'select count(*) from "{t}"').fetchone(), t
    log(f"backup {dst} integrity ok")
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("PLURIBUS_SQLITE_PATH", "./pluribus.db"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-backup", action="store_true", help="tests/scratch copies only")
    a = ap.parse_args()
    con = sqlite3.connect(a.db, isolation_level=None)
    p = plan(con)
    log(f"db {a.db}: legacy {p['legacy']} recreate {[n for n, _ in p['recreate']]} "
        f"missing-indexes {p['indexes']} extra-tables {p['extra']}")
    for n, w in p["recreate"]:
        log(f"  {n}: {w}")
    if not a.apply:
        log("dry run; --apply to migrate")
        return
    if not (p["legacy"] or p["recreate"] or p["indexes"]):
        log("nothing to do")
        return
    if not a.no_backup:
        backup(a.db)
    before = {t: con.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tables(con)}
    apply(con, p)
    after = {t: con.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tables(con)}
    for t, n in before.items():
        if t in LEGACY:
            assert after[LEGACY[t]] == n + before.get(LEGACY[t], 0)
        elif t not in LEGACY.values():
            assert after[t] == n, (t, n, after[t])
    rep = schema.drift_report(__import__("sqlalchemy").create_engine(f"sqlite:///{a.db}"))
    log(f"migrated; remaining drift {rep}")


if __name__ == "__main__":
    main()
