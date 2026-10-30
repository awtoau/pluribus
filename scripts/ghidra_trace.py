#!/usr/bin/env python3
"""One-call trace: group type / enum value / CRAM bit / function@vaddr / class -> the whole reversing chain (#169).  Docs: docs/reversing-lessons.md.

  python3 scripts/ghidra_trace.py trace <target> [--lib L] [--words N] [--ghidra]
  addresses = ELF vaddr (nm); --ghidra = hex target given in Ghidra form (+0x100000)
  target = group-type name (LE_LUT_FUNCTION) | enum:N | addr:0xA (raw bit value in the asmdb muxes) | <name-regex>@0xVADDR or 0xVADDR (function) | class:ASM_X

Chain printed (each section is one line group; offline, no Ghidra process):
  enum -> asmdb groups (class CALC/STD/DUMB/STL, block type, sites, mux kinds, bit sample + address space) -> bound ASM_* class (class_groups_table.json)
  -> writer functions (ctor, process_*), vtable slots, constructor data tables (dumped) -> readable file -> ledger rows (reference/rules.tsv) and errata that cite it.
Needs: `python3 scripts/ghidra_index.py build` (index.db); asmdb ddb from the Quartus install for the asmdb section.  Log: tmp/logs/ghidra_trace.log.
"""
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import ghidra_index as X  # noqa: E402

READ = os.path.join(X.AN, "readable")
GCLASS = {2: "BLOCK_INFO", 5: "CALC", 6: "STD", 7: "DUMB", 8: "STLMAP"}
MUXK = {12: "MUX", 14: "MAPPED_SIMPLE", 15: "ENCODED", 17: "SIMPLE", 18: "MAPPED_ENCODED", 19: "DECISION", 20: "HETERO_ENCODED",
        21: "ENCODED_BANK", 22: "RAM", 24: "STL_MAPPED_ENCODED"}
_walk = []


def out(s=""):
    print(s)


def walk():
    if not _walk:
        from lifters.cycloneiv_clean.asmdb_walk import Walk
        _walk.append(Walk())
    return _walk[0]


def space_of(v):
    from lifters.cycloneiv_clean import cycloneiv_io as IO
    s, i = IO.classify([v])
    return f"{s[0]}:{int(i[0])}"


def ledger_rows(terms):
    """reference/rules.tsv + docs/reversing-errata.md rows that cite any term (case-sensitive substring)."""
    rows = []
    for f, label in (("reference/rules.tsv", "rules"), ("docs/reversing-errata.md", "errata")):
        p = os.path.join(REPO, f)
        if not os.path.exists(p):
            continue
        for line in open(p):
            if any(t and t in line for t in terms):
                rows.append((label, line.split("\t")[0] if label == "rules" else line.split("|")[1].strip(), line))
    return rows


def readable(lib, cls):
    for l in ([lib] if lib else []) + [d for d in os.listdir(READ) if os.path.isdir(os.path.join(READ, d))] if os.path.isdir(READ) else []:
        p = os.path.join(READ, l, cls.replace("::", "_") + ".c")
        if os.path.exists(p):
            return os.path.relpath(p, REPO)
    return None


def sec_class(db, cls, lib=None, words=48):
    out(f"== class {cls}")
    fs = db.execute("select distinct lib, vaddr, name from functions where cls=? order by lib, vaddr", (cls,)).fetchall()
    base = cls.rsplit("::", 1)[-1]
    for l, va, n in fs:
        tag = "writer" if re.search(r"::(process_\w+|write_\w+|set_\w+|" + re.escape(base) + r")\(", n) else "method"
        if tag == "writer" or len(fs) <= 12:
            out(f"  {tag}\t{l}\t0x{va:x}\t{n}")
    if len(fs) > 12:
        out(f"  ({len(fs)} methods in total: ghidra_index.py func '^{cls}::')")
    vs = db.execute("select lib, off, target, vaddr from vtslots where cls=? order by off", (cls,)).fetchall()
    if vs:
        out(f"  vtable slots ({len(vs)}):")
        for l, off, tg, va in vs[:40]:
            out(f"    +0x{off:x}\t{tg}\t0x{va:x}" if va is not None else f"    +0x{off:x}\t{tg}")
        if len(vs) > 40:
            out(f"    ... {len(vs) - 40} more (reference/ghidra/vtables.tsv)")
    for r in db.execute("select distinct lib from functions where cls=?", (cls,)):
        sys.stdout.flush()
        try:
            import ghidra_dump as D
            L = D.Lib(r[0])
            out(f"  constructor tables ({r[0]}):")
            import io
            import contextlib
            b = io.StringIO()
            with contextlib.redirect_stdout(b):
                D.ctor_tables(L, cls, words)
            for ln in b.getvalue().splitlines()[:120]:
                out("    " + ln)
        except SystemExit:
            pass
        break
    rp = readable(lib, cls)
    out(f"  readable: {rp or '(none exported)'}")
    return fs


def sec_group(db, what, lib, words):
    for en, val, name in X.enum_sel(db, what):
        out(f"== enum {en} {val} {name}")
        names = {v: n for e, v, n in db.execute("select enum,value,name from enums where enum='ASMDB_ARCH_GROUP_BLOCK_TYPE'")}
        try:
            w = walk()
            gs = [g for g in w.groups() if g["type"] == val]
        except Exception as e:      # noqa: BLE001  (ddb missing on this box)
            gs = []
            out(f"  asmdb: unavailable ({e})")
        if gs:
            out(f"  asmdb: {len(gs)} group objects")
        for g in gs[:6]:
            site_n = len(g["bits"]) if g["cls"] == 7 else len(g.get("paths", []))
            kinds = set()
            if g["cls"] != 7 and g.get("paths"):
                for ref in (g["paths"][0] or []):
                    if ref:
                        kinds.add(MUXK.get(w.mux(ref)["cls"], str(w.mux(ref)["cls"])))
            from lifters.cycloneiv_clean.asmdb_walk import _site_bits
            bits = _site_bits(w, g, 0) if site_n else []
            out(f"    gi={g['gi']} {GCLASS.get(g['cls'], g['cls'])} block={names.get(g['btype'], g['btype'])}({g['btype']}) sites={site_n} "
                f"mux={','.join(sorted(kinds)) or '-'} site0 bits[{len(bits)}]: " + " ".join(space_of(b) for b in bits[:6]))
        if len(gs) > 6:
            out(f"    ... {len(gs) - 6} more (same type, other block types)")
        terms = [name, f"enum {val}"]
        clss = db.execute("select distinct cls, lib, factory, source from groups where value=?", (val,)).fetchall()
        if not clss:
            out("  bound class: none in class_groups_table.json (group written by a non-factory path: search with enum-users / strings-grep)")
        for cls, l, fac, src in clss:
            out(f"  bound class {cls} ({l}) via {fac} [{src}]")
            terms.append(cls)
            sec_class(db, cls, l, words)
        shown = {c[0] for c in clss}
        for (cls,) in db.execute("select distinct cls from functions where cls regexp ?", (r"^ASM\w*?_" + re.escape(name) + "$",)).fetchall():
            if cls not in shown:     # factory binds a holder class (e.g. ASM_LAB_ARCH_GROUP); the writer is named after the group
                out(f"  name-convention class {cls} (writer named after the group; factory-bound class is only a holder)")
                terms.append(cls)
                sec_class(db, cls, None, words)
        for t in terms[:1] + [c for c in terms if c.startswith("ASM")]:
            for k, ml, r, f, v, st in db.execute("select kind, lib, ref, fact, verified, status from mined where ref like ?", (f"%{t}%",)):
                out(f"  mined[{k},{st}] {r[:70]}: {f[:140]}")
        for lab, i, line in ledger_rows(terms):
            out(f"  ledger[{lab}] {i}: {line.strip()[:200]}")


def sec_func(db, what, lib, ghidra=False):
    """Addresses are ELF vaddr (= nm); Ghidra shows +0x100000.  --ghidra: the hex target is Ghidra form and is normalised to ELF."""
    m = re.match(r"^(.*)@(0x[0-9a-fA-F]+)$", what)
    sel = m.group(2) if m else what
    if ghidra and re.fullmatch(r"0x[0-9a-fA-F]+", sel):
        sel = f"0x{int(sel, 16) - 0x100000:x}"
        out(f"(Ghidra form {m.group(2) if m else what} normalised to ELF {sel})")
    fs = X.fn_sel(db, sel, lib)
    if m and m.group(1):
        fs = [f for f in fs if re.search(m.group(1), f[2])] or fs
    for l, va, nm in fs[:10]:
        out(f"== function {l} 0x{va:x} (Ghidra 0x{va + 0x100000:x}) {nm}")
        if not ghidra and re.fullmatch(r"0x[0-9a-fA-F]+", sel):
            alt = db.execute("select name from functions where lib=? and vaddr=?", (l, va - 0x100000)).fetchone() if va >= 0x100000 else None
            if alt:
                out(f"  note: ELF 0x{va - 0x100000:x} is {alt[0]}; if your address came from the Ghidra GUI rerun with --ghidra")
        for c in X.tsv_rows("twins.tsv"):
            if c[0] == l and int(c[1], 16) == va or c[0] == l and int(c[2], 16) == va:
                out(f"  PLT stub pair: real function 0x{c[1]}, stub 0x{c[2]} ({c[3]}; cite the real function)")
        cls = X.class_of(nm)
        if cls:
            groups = db.execute("select distinct value, grp from groups where cls=?", (cls,)).fetchall()
            for v, g in groups:
                out(f"  class {cls} writes group {g} (enum {v})")
        for r in db.execute("select e.ext, e.callee, f.name from edges e left join functions f on f.lib=e.lib and f.vaddr=e.callee where e.lib=? and e.caller=? limit 40", (l, va)):
            out(f"  calls {('ext ' + r[0]) if r[0] else '0x%x %s' % (r[1], r[2])}")
        for r in db.execute("select e.caller, f.name from edges e left join functions f on f.lib=e.lib and f.vaddr=e.caller where e.lib=? and e.callee=? limit 40", (l, va)):
            out(f"  called by 0x{r[0]:x} {r[1]}")
        for r in db.execute("select distinct cls, off, target from vtslots where lib=? and vaddr=?", (l, va)):
            out(f"  vtable slot {r[0]} +0x{r[1]:x}")
        for r in db.execute("select saddr, text from strings where lib=? and func=? limit 12", (l, va)):
            out(f"  string 0x{r[0]:x} {r[1][:80]!r}")
        for k, ml, r, f, v, st in db.execute("select kind, lib, ref, fact, verified, status from mined where ref like ? or ref like ?", (f"%0x{va:x}%", f"%{nm.split('(')[0]}%")):
            out(f"  mined[{k},{st}] {r[:70]}: {f[:140]}")
        for lab, i, line in ledger_rows([f"0x{va:x}", f"@{va:x}", nm.split("(")[0]]):
            out(f"  ledger[{lab}] {i}: {line.strip()[:200]}")
        if cls:
            rp = readable(l, cls)
            out(f"  readable: {rp or '(none)'}")
    if not fs:
        out(f"no function matches {what}")


def sec_addr(db, v):
    w = walk()
    from lifters.cycloneiv_clean.asmdb_walk import _site_bits
    names = {x: n for _, x, n in db.execute("select enum,value,name from enums where enum='ASMDB_ARCH_GROUP_TYPE'")}
    out(f"== raw bit value {v:#x} = {space_of(v)}")
    hits = 0
    for g in w.groups():
        if g["cls"] not in (5, 6, 7, 8):
            continue
        n = len(g["bits"]) if g["cls"] == 7 else len(g.get("paths", []))
        for s in range(n):
            if v in _site_bits(w, g, s):
                hits += 1
                if hits <= 40:
                    out(f"  group {names.get(g['type'], g['type'])} ({g['type']}) {GCLASS[g['cls']]} block {g['btype']} site {s}")
    out(f"  {hits} (group, site) hits" + ("" if hits else ": block-relative groups (LAB/MEAB) store offsets; try the offset, not the absolute address"))


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] != "trace":
        print(__doc__)
        return 2
    lib = a[a.index("--lib") + 1] if "--lib" in a else None
    words = int(a[a.index("--words") + 1]) if "--words" in a else 48
    gh = "--ghidra" in a
    t = a[1]
    db = X.connect()
    if "@" in t:
        sec_func(db, t, lib, gh)
    elif t.startswith("addr:"):
        sec_addr(db, int(t[5:], 0))
    elif t.startswith("enum:"):
        sec_group(db, t[5:], lib, words)
    elif t.startswith("class:") or db.execute("select 1 from functions where cls=? limit 1", (t,)).fetchone():
        c = t[6:] if t.startswith("class:") else t
        sec_class(db, c, lib, words)
        for v, g in db.execute("select distinct value, grp from groups where cls=?", (c,)):
            out(f"  writes group {g} (enum {v})")
    elif re.fullmatch(r"0x[0-9a-fA-F]+", t):
        sec_func(db, t, lib, gh)
    elif X.enum_sel(db, t):
        sec_group(db, t, lib, words)
    else:
        sec_func(db, t, lib)
    return 0


if __name__ == "__main__":
    sys.exit(main())
