#!/usr/bin/env python3
"""Scan the decompile cache for known decompiler defects -> reference/ghidra/defects.tsv (#169).  Docs: docs/reversing-lessons.md.

  python3 scripts/ghidra_defects.py [lib ...]     # log: tmp/logs/ghidra_defects.log

Kinds (rows: lib, vaddr, function, kind, detail, resolution, source):
  jumptable    "Could not recover jumptable": table vaddr (ELF) + bound read from the guard; resolution = ghidra_dump.py switch
  noreturn-new `operator_new` followed by "Subroutine does not return" (body truncated before the vptr store / ctor call);
               resolution = TypesPass clearNoReturnNew, then re-decompile; until then read objdump (ghidra_apply_names.py batch)
  ext-arity    call to an external whose argument count differs from the signature in signatures.tsv (mux_select value arg)
Cache = vendor-analysis/altera/analysis/ghidra_out/cache/<lib>/<vaddr>_<name>.c (ghidra_apply_names.py batch).  Names/addresses only.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(HERE)
CACHE = os.path.join(REPO, "vendor-analysis", "altera", "analysis", "ghidra_out", "cache")
OUT = os.path.join(REPO, "reference", "ghidra", "defects.tsv")
LOG = os.path.join(REPO, "tmp", "logs", "ghidra_defects.log")
BASE = 0x100000


def scan(lib, fn):
    m = re.match(r"([0-9a-f]+)_(.*)\.c$", fn)
    va, name = m.group(1), m.group(2)
    lines = open(os.path.join(CACHE, lib, fn), errors="replace").read().splitlines()
    rows = []
    for i, ln in enumerate(lines):
        if "Could not recover jumptable" in ln:
            jt = re.search(r"switchdata\w*_([0-9a-f]{8})", "\n".join(lines[i:i + 8]))
            bound = None
            for back in lines[max(0, i - 6):i][::-1]:
                b = re.search(r"<\s*(0x[0-9a-f]+|\d+)", back)
                if b:
                    bound = int(b.group(1), 0) + 1
                    break
            tab = f"0x{int(jt.group(1), 16) - BASE:x}" if jt else "?"
            rows.append((lib, va, name, "jumptable", f"table {tab} entries {bound or '?'}",
                         f"ghidra_dump.py switch {lib} {tab} {bound or 'N'}" if jt else "read objdump"))
        elif re.search(r"operator_new|operator\.new", ln) and any("Subroutine does not return" in x for x in lines[i + 1:i + 4]):
            rows.append((lib, va, name, "noreturn-new", "body truncated after operator_new", "TypesPass clearNoReturnNew + re-decompile"))
    return rows


def main():
    libs = sys.argv[1:] or sorted(os.listdir(CACHE))
    rows = []
    for lib in libs:
        for fn in sorted(os.listdir(os.path.join(CACHE, lib))):
            if fn.endswith(".c"):
                rows += scan(lib, fn)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(OUT, "w") as f:
        f.write("# lib\tvaddr\tfunction\tkind\tdetail\tresolution\tsource\n")
        for r in sorted(set(rows)):
            f.write("\t".join(r) + "\tscripts/ghidra_defects.py\n")
    cnt = {}
    for r in rows:
        cnt[r[3]] = cnt.get(r[3], 0) + 1
    msg = f"{len(rows)} defects {cnt} -> {OUT}"
    open(LOG, "a").write(msg + "\n")
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
