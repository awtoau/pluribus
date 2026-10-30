#!/usr/bin/env python3
"""Generate reference/ghidra/enums.tsv from the vendor libs' debug-string tables (#165, #168).

  python3 scripts/ghidra_gen_enums.py        # log: tmp/logs/ghidra_gen_enums.log

Each table is char*[N] (index = enum value); pointers come from .rela.dyn R_X86_64_RELATIVE addends into .rodata.
Rows: lib, enum, value, name, source.  Same name twice in one enum -> second gets `_<value>`.
Names only (vendor-published debug strings); no binaries in the TSV.
"""
import logging
import os
import sys

from elftools.elf.elffile import ELFFile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(HERE)
QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
OUT = os.path.join(REPO, "reference", "ghidra", "enums.tsv")
LOG = os.path.join(REPO, "tmp", "logs", "ghidra_gen_enums.log")
# (lib, symbol, enum, value width)
TABLES = [
    ("libdb_asmdb", "ASMDB_TRANSLATOR::m_asmdb_arch_group_type_debug_string_table", "ASMDB_ARCH_GROUP_TYPE"),
    ("libdb_asmdb", "ASMDB_TRANSLATOR::m_asmdb_arch_group_block_type_debug_string_table", "ASMDB_ARCH_GROUP_BLOCK_TYPE"),
    ("libdb_asmdb", "ASMDB_TRANSLATOR::m_asmdb_dirt_type_debug_string_table", "ASMDB_DIRT_TYPE"),
    ("libddb_dstr", "DSTR_TRANSLATOR::m_dev_element_enum_debug_string_table", "DEV_ELEMENT_ENUM"),
]


def symbols(path):
    """symbol (demangled via nm -C) -> (vaddr, size) for the data tables above."""
    import subprocess
    r = subprocess.run(["nm", "-C", "-S", "-D", path], capture_output=True, text=True, check=True)
    out = {}
    for ln in r.stdout.splitlines():
        p = ln.split(None, 3)
        if len(p) == 4 and p[2] in "dD":
            out[p[3]] = (int(p[0], 16), int(p[1], 16))
    return out


def read_table(path, addr, size):
    e = ELFFile(open(path, "rb"))
    ro = e.get_section_by_name(".rodata")
    data, base = ro.data(), ro["sh_addr"]
    out = {}
    for r in e.get_section_by_name(".rela.dyn").iter_relocations():
        o = r["r_offset"]
        if addr <= o < addr + size:
            a = r["r_addend"] - base
            if 0 <= a < len(data):
                out[(o - addr) // 8] = data[a:data.index(0, a)].decode("ascii", "replace")
    return out


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = logging.getLogger("gen_enums")
    log.addHandler(logging.FileHandler(LOG))
    log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)
    rows, cache = [], {}
    for lib, sym, enum in TABLES:
        path = os.path.join(QROOT, "linux64", lib + ".so")
        if path not in cache:
            cache[path] = symbols(path)
        if sym not in cache[path]:
            log.error("%s: symbol %s missing", lib, sym)
            return 1
        addr, size = cache[path][sym]
        tab = read_table(path, addr, size)
        seen = set()
        n = 0
        for v in sorted(tab):
            name = tab[v]
            if not name or not name.replace("_", "").isalnum():
                continue
            if name in seen:
                name = f"{name}_{v}"
            seen.add(name)
            rows.append((lib, enum, v, name, f"{lib}:{sym} (vaddr {addr:#x})"))
            n += 1
        log.info("%s %s: %d of %d slots named", lib, enum, n, size // 8)
    with open(OUT, "w") as f:
        f.write("# lib\tenum\tvalue\tname\tsource\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    log.info("wrote %d rows -> %s", len(rows), OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
