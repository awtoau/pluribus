#!/usr/bin/env python3
"""Searchable SQLite index over the Quartus libs (#169).  Docs: docs/reversing-lessons.md.

  python3 scripts/ghidra_index.py build [lib ...]        # ELF symbols + enums + bindings + vtables (+ Ghidra feed if present)
  python3 scripts/ghidra_index.py func <regex>           # functions by demangled name
  python3 scripts/ghidra_index.py callers|callees <name|0xVADDR> [lib]
  python3 scripts/ghidra_index.py strings-grep <regex>   # strings with referencing functions (needs the Ghidra feed)
  python3 scripts/ghidra_index.py enum-users <enum-name|value>    # group, class, ctor/process functions, readable files, ledger rows
  python3 scripts/ghidra_index.py find-writers-of <enum-name|value>   # classes + functions that write the group
  python3 scripts/ghidra_index.py data <regex>           # data symbols (tables, vtables, typeinfo)
  python3 scripts/ghidra_index.py mined [regex] [kind]   # reference/ghidra/mined.tsv facts (function enum rule finding retraction table negative struct)
  python3 scripts/ghidra_index.py stats

DB: vendor-analysis/altera/analysis/index.db (gitignored, derived: delete and rebuild, no migration).  Feed (call edges, string xrefs):
`python3 scripts/ghidra_apply_names.py index-feed` -> analysis/index/<lib>.tsv.  Log: tmp/logs/ghidra_index.log.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(HERE)
QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
AN = os.path.join(REPO, "vendor-analysis", "altera", "analysis")
DB = os.environ.get("PLURIBUS_INDEX_DB") or os.path.join(AN, "index.db")
FEED = os.path.join(AN, "index")
TSV = os.path.join(REPO, "reference", "ghidra")
GROUPS = os.path.join(REPO, "lifters", "cycloneiv_clean", "class_groups_table.json")
LOG = os.path.join(REPO, "tmp", "logs", "ghidra_index.log")

SCHEMA = """
create table libs(name text primary key, tier text);
create table functions(lib text, vaddr integer, size integer, name text, cls text, src text);
create table data(lib text, vaddr integer, size integer, name text, typ text);
create table edges(lib text, caller integer, callee integer, ext text);
create table strings(lib text, func integer, saddr integer, text text);
create table dataref(lib text, func integer, daddr integer);
create table enums(lib text, enum text, value integer, name text, source text);
create table groups(value integer, grp text, cls text, lib text, factory text, source text);
create table mined(kind text, lib text, ref text, fact text, src text, verified text, status text);
create table vtslots(lib text, cls text, off integer, target text, vaddr integer, source text);
create index f_n on functions(name); create index f_c on functions(cls); create index f_v on functions(lib, vaddr);
create index d_n on data(name); create index e_c on edges(lib, caller); create index e_t on edges(lib, callee);
create index s_f on strings(lib, func); create index en_n on enums(name); create index en_v on enums(enum, value);
create index g_v on groups(value); create index g_c on groups(cls); create index v_c on vtslots(cls);
"""


def log(m):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(m + "\n")
    print(m)


def tsv_rows(name):
    p = os.path.join(TSV, name)
    if os.path.exists(p):
        for line in open(p):
            if line.strip() and not line.startswith("#"):
                yield line.rstrip("\n").split("\t")


def libs_list():
    from_tsv = {c[0][:-3] if c[0].endswith(".so") else c[0]: c[7] for c in tsv_rows("libs.tsv") if len(c) > 7}
    out = {k: v for k, v in from_tsv.items() if v == "core"}
    return out


def lib_path(lib):
    d = os.path.join(QROOT, "linux64")
    p = os.path.join(d, lib + ".so")
    return p if os.path.exists(p) else os.path.join(d, lib)


def class_of(name):
    n = re.sub(r"^(non-virtual thunk to |virtual thunk to |covariant return thunk to )", "", name)
    n = re.sub(r"^(vtable for |typeinfo for |typeinfo name for |VTT for )", "", n)
    depth, cut = 0, None
    for i, ch in enumerate(n):          # first '(' at template depth 0 ends the qualified name
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "(" and depth == 0:
            cut = i
            break
    q = n[:cut] if cut is not None else n
    depth = 0
    for i in range(len(q) - 1, 1, -1):  # last '::' at depth 0
        if q[i] == ">":
            depth += 1
        elif q[i] == "<":
            depth -= 1
        elif q[i] == ":" and q[i - 1] == ":" and depth == 0:
            return q[:i - 1]
    return ""


def load_elf(db, lib):
    r = subprocess.run(["nm", "-C", "-S", "--defined-only", lib_path(lib)], capture_output=True, text=True)
    nf = nd = 0
    for line in r.stdout.splitlines():
        m = re.match(r"^([0-9a-f]+) (?:([0-9a-f]+) )?(\w) (.*)$", line)
        if not m:
            continue
        va, size, typ, name = int(m.group(1), 16), int(m.group(2) or "0", 16), m.group(3), m.group(4)
        if typ in "Tt" or (typ in "Ww" and "(" in name):
            db.execute("insert into functions values(?,?,?,?,?,?)", (lib, va, size, name, class_of(name), "elf"))
            nf += 1
        else:
            db.execute("insert into data values(?,?,?,?,?)", (lib, va, size, name, typ))
            nd += 1
    return nf, nd


def load_feed(db, lib):
    p = os.path.join(FEED, lib + ".tsv")
    if not os.path.exists(p):
        return 0
    n = 0
    for line in open(p, errors="replace"):
        c = line.rstrip("\n").split("\t")
        k = c[0]
        if k == "F" and len(c) >= 4:
            va = int(c[1], 16)
            if not db.execute("select 1 from functions where lib=? and vaddr=?", (lib, va)).fetchone():
                db.execute("insert into functions values(?,?,?,?,?,?)", (lib, va, int(c[2]), c[3], class_of(c[3]), "ghidra"))
        elif k == "E" and len(c) >= 3:
            ext = c[2][4:] if c[2].startswith("ext:") else None
            db.execute("insert into edges values(?,?,?,?)", (lib, int(c[1], 16), None if ext else int(c[2], 16), ext))
        elif k == "S" and len(c) >= 4:
            db.execute("insert into strings values(?,?,?,?)", (lib, int(c[1], 16), int(c[2], 16), c[3]))
        elif k == "R" and len(c) >= 3:
            db.execute("insert into dataref values(?,?,?)", (lib, int(c[1], 16), int(c[2], 16)))
        else:
            continue
        n += 1
    return n


def build(only):
    if os.path.exists(DB):
        os.remove(DB)          # derived artifact: rebuild is the migration
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    libs = libs_list()
    sys.path.insert(0, HERE)
    import ghidra_apply_names as G
    for l in G.ALL_LIBS:
        libs.setdefault(l, "core")
    for lib in sorted(libs):
        if only and lib not in only:
            continue
        if not os.path.exists(lib_path(lib)):
            continue
        db.execute("insert into libs values(?,?)", (lib, libs[lib]))
        nf, nd = load_elf(db, lib)
        nfeed = load_feed(db, lib)
        log(f"{lib}: functions={nf} data={nd} feed_rows={nfeed}")
        db.commit()
    for c in tsv_rows("enums.tsv"):
        db.execute("insert into enums values(?,?,?,?,?)", (c[0], c[1], int(c[2]), c[3], c[4]))
    for c in tsv_rows("mined.tsv"):          # transcript-mined facts (kinds: function enum rule finding retraction table negative struct)
        c = (c + [""] * 7)[:7]
        db.execute("insert into mined values(?,?,?,?,?,?,?)", c)
    if os.path.exists(GROUPS):
        for g in json.load(open(GROUPS)):
            db.execute("insert into groups values(?,?,?,?,?,?)", (g["enum"], g["group"], g["cls"], g["lib"], g.get("factory", ""), g.get("source", "")))
    import ghidra_gen_vtables as V
    for lib in sorted(libs):
        if only and lib not in only or not os.path.exists(os.path.join(QROOT, "linux64", lib + ".so")):
            continue
        for c in V.rows_for(lib)[0]:
            db.execute("insert into vtslots values(?,?,?,?,?,?)", (c[0], c[1], int(c[2], 16), c[3], int(c[4], 16), c[5]))
    for c in tsv_rows("vtables.tsv"):       # curated rows only (elf: rows are regenerated above)
        if len(c) >= 6 and not c[3].startswith("alias:") and not c[5].startswith("elf:"):
            try:
                db.execute("insert into vtslots values(?,?,?,?,?,?)", (c[0], c[1], int(c[2], 16), c[3], int(c[4], 16) if c[4] else None, c[5]))
            except ValueError:
                pass
    db.commit()
    log("built " + DB)
    stats(db)
    return 0


def stats(db):
    for t in ("libs", "functions", "data", "edges", "strings", "dataref", "enums", "groups", "vtslots", "mined"):
        print(f"  {t}: {db.execute(f'select count(*) from {t}').fetchone()[0]}")


def connect():
    if not os.path.exists(DB):
        sys.exit(f"{DB} missing: python3 scripts/ghidra_index.py build")
    db = sqlite3.connect(DB)
    db.create_function("regexp", 2, lambda p, s: 1 if s is not None and re.search(p, s) else 0)
    return db


def fn_sel(db, what, lib=None):
    """name substring / regex / 0xVADDR -> [(lib, vaddr, name)]"""
    q = "select lib, vaddr, name from functions where "
    if re.fullmatch(r"0x[0-9a-fA-F]+", what):
        q += "vaddr=?"
        a = [int(what, 16)]
    else:
        q += "name regexp ?"
        a = [what]
    if lib:
        q += " and lib=?"
        a.append(lib)
    return db.execute(q, a).fetchall()


def edges_of(db, what, lib, out):
    for l, va, nm in fn_sel(db, what, lib):
        print(f"# {l} 0x{va:x} {nm}")
        if out:
            rows = db.execute("select e.callee, e.ext, f.name from edges e left join functions f on f.lib=e.lib and f.vaddr=e.callee where e.lib=? and e.caller=?", (l, va)).fetchall()
            for cal, ext, n in rows:
                print(f"  -> {'ext ' + ext if ext else '0x%x %s' % (cal, n or '?')}")
        else:
            rows = db.execute("select e.caller, f.name from edges e left join functions f on f.lib=e.lib and f.vaddr=e.caller where e.lib=? and e.callee=?", (l, va)).fetchall()
            for cal, n in rows:
                print(f"  <- 0x{cal:x} {n or '?'}")
            base = nm.split("(")[0].split("::")[-1]       # calls from other libs are external stubs known by the unqualified name only
            x = db.execute("select e.lib, e.caller, f.name from edges e left join functions f on f.lib=e.lib and f.vaddr=e.caller where e.ext=? and e.lib<>? limit 300", (base, l)).fetchall()
            for xl, cal, n in x:
                print(f"  <- (cross-lib, by name '{base}') {xl} 0x{cal:x} {n or '?'}")


def enum_sel(db, what):
    if re.fullmatch(r"(0x[0-9a-fA-F]+|\d+)", what):
        return db.execute("select enum, value, name from enums where value=? and enum='ASMDB_ARCH_GROUP_TYPE'", (int(what, 0),)).fetchall()
    return db.execute("select enum, value, name from enums where name=? or name regexp ?", (what, "^" + what + "$")).fetchall()


def writers(db, what):
    out = []
    for en, val, name in enum_sel(db, what) or [("?", None, what)]:
        gs = db.execute("select value, grp, cls, lib, factory, source from groups where value=? or grp=?", (val, name)).fetchall()
        out.append((en, val, name, gs))
    return out


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 2
    cmd, rest = a[0], a[1:]
    if cmd == "build":
        return build(set(rest))
    db = connect()
    if cmd == "stats":
        stats(db)
    elif cmd == "func":
        for l, va, n in fn_sel(db, rest[0]):
            print(f"{l}\t0x{va:x}\t{n}")
    elif cmd in ("callers", "callees"):
        edges_of(db, rest[0], rest[1] if len(rest) > 1 else None, cmd == "callees")
    elif cmd == "strings-grep":
        for l, f, sa, t, fn in db.execute("select s.lib, s.func, s.saddr, s.text, f.name from strings s left join functions f on f.lib=s.lib and f.vaddr=s.func where s.text regexp ? limit 500", (rest[0],)):
            print(f"{l}\t0x{sa:x}\t{t[:100]!r}\t0x{f:x} {fn}")
    elif cmd == "mined":    # mined [regex] [kind]: transcript-mined facts matching the regex
        q = "select kind, lib, ref, fact, verified, status from mined where (ref regexp ? or fact regexp ?)"
        a = [rest[0], rest[0]] if rest else [".", "."]
        if len(rest) > 1:
            q += " and kind=?"
            a.append(rest[1])
        for k, l, r, f, v, st in db.execute(q, a):
            print(f"{k}\t{l}\t{r}\t{f[:160]}\t[{st}; {v[:40]}]")
    elif cmd == "data":
        for l, va, sz, n, t in db.execute("select lib, vaddr, size, name, typ from data where name regexp ? limit 500", (rest[0],)):
            print(f"{l}\t0x{va:x}\t{sz}\t{t}\t{n}")
    elif cmd in ("find-writers-of", "enum-users"):
        for en, val, name, gs in writers(db, rest[0]):
            print(f"# {en} {val} {name}")
            for v, grp, cls, lib, fac, src in gs:
                print(f"  class {cls} ({lib}) factory {fac}  [{src}]")
                for l, va, n in db.execute("select lib, vaddr, name from functions where cls=? order by vaddr", (cls,)):
                    base = cls.rsplit("::", 1)[-1]
                    if re.search(r"::(process_\w+|write_\w+|set_\w+|" + re.escape(base) + r")\(", n):
                        print(f"    writer {l} 0x{va:x} {n}")
            if cmd == "enum-users":
                for l, va, n in db.execute("select s.lib, s.func, f.name from strings s join functions f on f.lib=s.lib and f.vaddr=s.func where s.text=? limit 50", (name,)):
                    print(f"  string-xref {l} 0x{va:x} {n}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
