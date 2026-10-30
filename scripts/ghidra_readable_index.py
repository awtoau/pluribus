#!/usr/bin/env python3
"""Generate docs/ghidra-readable-index.md: names, addresses, one-line purpose, clean-tree users.  (#165, #168)

  python3 scripts/ghidra_readable_index.py     # log: tmp/logs/ghidra_readable_index.log
Sources: reference/ghidra/*.tsv, vendor-analysis/altera/analysis/readable/<lib>/*.c (counted, never quoted).
No decompiled bodies are written.
"""
import glob
import os
import re

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TSV = os.path.join(REPO, "reference", "ghidra")
READ = os.path.join(REPO, "vendor-analysis", "altera", "analysis", "readable")
OUT = os.path.join(REPO, "docs", "ghidra-readable-index.md")


def rows(name):
    p = os.path.join(TSV, name)
    return [l.rstrip("\n").split("\t") for l in open(p) if l.strip() and not l.startswith("#")] if os.path.exists(p) else []


def users(cls):
    pat = re.compile(re.escape(cls))
    hits = []
    for f in glob.glob(os.path.join(REPO, "lifters", "cycloneiv_clean", "*.py")) + glob.glob(os.path.join(REPO, "scripts", "cycloneiv_clean*.py")):
        if pat.search(open(f, errors="replace").read()):
            hits.append(os.path.relpath(f, REPO))
    return ", ".join(sorted(hits)[:3]) or "-"


def main():
    L = ["# Ghidra readable-code index (#165, #168)", "",
         "Names, addresses and purposes only; pseudo-code is local under `vendor-analysis/altera/analysis/readable/` (gitignored). "
         "How to build it: [ghidra-workflow.md](ghidra-workflow.md).", "",
         "## Layers", ""]
    enums = {}
    for r in rows("enums.tsv"):
        enums[r[1]] = enums.get(r[1], 0) + 1
    L += ["| Enum | Constants | Source table |", "|---|---|---|"]
    for e, n in sorted(enums.items()):
        L.append(f"| `{e}` | {n} | `enums.tsv` (vendor debug-string table) |")
    vt = {}
    for r in rows("vtables.tsv"):
        vt.setdefault(r[0], set()).add(r[1])
    st = {}
    for r in rows("structs.tsv"):
        st.setdefault(r[0], set()).add(r[1])
    L += ["", "## Per library", "", "| Lib | Classes with vtable | Mined structs | Exported class files |", "|---|---|---|---|"]
    for lib in sorted(set(vt) | set(st) | {os.path.basename(d) for d in glob.glob(os.path.join(READ, "lib*"))}):
        if lib == "*":
            continue
        n = len(glob.glob(os.path.join(READ, lib, "*.c")))
        L.append(f"| {lib} | {len(vt.get(lib, ()))} | {len(st.get(lib, ()))} | {n} |")
    L += ["", "## Key functions", "", "| Lib | Vaddr | Function | Purpose | Clean-tree user |", "|---|---|---|---|---|"]
    seen = set()
    for f in ("signatures.tsv", "functions.tsv"):
        for r in rows(f):
            if len(r) < 4 or (r[0], r[1]) in seen or not r[2]:
                continue
            seen.add((r[0], r[1]))
            purpose = (r[5] if len(r) > 5 else "").split(".")[0][:110] or "-"
            L.append(f"| {r[0]} | `0x{r[1].replace('0x', '')}` | `{r[2]}` | {purpose} | {users(r[2].split('::')[0])} |")
    L += ["", "## Struct classes (serializer-mined)", "", "| Lib | Struct | Size | Fields |", "|---|---|---|---|"]
    sz = {}
    for r in rows("structs.tsv"):
        k = (r[0], r[1])
        sz.setdefault(k, [r[2], set()])[1].add(r[3])
    for (lib, s), (size, fl) in sorted(sz.items()):
        L.append(f"| {lib} | `{s}` | {size} | {len(fl)} |")
    open(OUT, "w").write("\n".join(L) + "\n")
    print(f"wrote {OUT}: {len(seen)} key functions")


if __name__ == "__main__":
    main()
