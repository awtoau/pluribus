#!/usr/bin/env python3
"""Generate reference/ghidra/vtables.tsv from the vendor libs' `vtable for X` symbols (#165, #168).

  python3 scripts/ghidra_gen_vtables.py [lib ...]     # log: tmp/logs/ghidra_gen_vtables.log

Rows: lib, class, offset (hex, relative to the vptr = vtable symbol + 0x10), slot method, target vaddr, source.
Primary vtable only (stops at the first non-.text slot = next typeinfo). Pure virtuals are skipped.
Rows whose source does not start with `elf:` (curated, e.g. PDB_SEGMENT_READER call offsets) are kept.
"""
import logging
import os
import subprocess
import sys

from elftools.elf.elffile import ELFFile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(HERE)
QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
OUT = os.path.join(REPO, "reference", "ghidra", "vtables.tsv")
LOG = os.path.join(REPO, "tmp", "logs", "ghidra_gen_vtables.log")
LIBS = ["libcomp_asm", "libcomp_asm2", "libcomp_asmcc", "libcomp_asmgx", "libdb_asmdb", "libddb_dev",
        "libddb_dygr", "libddb_dstr", "libpgm_pgmio", "libpgm_npcf", "libdb_pdb", "libcomp_asmio", "libcomp_asmram",
        "libcomp_asmmac", "libcomp_asmpll", "libdb_cdb_atom_stingray", "libddb_bcm2bits", "libdb_u2b_bcm", "libddb_dbcm",
        "libpgm_fbgen", "libpgm_pof", "libdb_cut", "libdb_cdb_atom_ygr"]


def strip_args(n):
    depth = 0
    for i, ch in enumerate(n):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "(" and depth == 0:
            return n[:i]
    return n


def nm_symbols(path):
    r = subprocess.run(["nm", "-C", "-S", path], capture_output=True, text=True, check=True)
    vt, fn = {}, {}
    for ln in r.stdout.splitlines():
        p = ln.split(None, 3)
        if len(p) == 4 and (p[2] in "VvTtWw" or p[3].startswith("vtable for ")):
            a, sz, name = int(p[0], 16), int(p[1], 16), p[3]
            if name.startswith("vtable for "):
                vt[name[11:]] = (a, sz)
            elif p[2] in "TtWw":
                fn.setdefault(a, strip_args(name))
        elif len(p) == 3 and p[1] in "TtWw":
            fn.setdefault(int(p[0], 16), strip_args(p[2]))
    return vt, fn


def main():
    libs = sys.argv[1:] or LIBS
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = logging.getLogger("gen_vtables")
    log.addHandler(logging.FileHandler(LOG))
    log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)
    keep = []
    if os.path.exists(OUT):
        for ln in open(OUT):
            c = ln.rstrip("\n").split("\t")
            if ln.startswith("#") or not ln.strip():
                continue
            if len(c) >= 6 and not c[5].startswith("elf:") and c[0] not in libs:
                keep.append(ln)
            elif len(c) >= 6 and not c[5].startswith("elf:"):
                keep.append(ln)
    rows = []
    for lib in libs:
        path = os.path.join(QROOT, "linux64", lib + ".so")
        vt, fn = nm_symbols(path)
        e = ELFFile(open(path, "rb"))
        text = e.get_section_by_name(".text")
        t0, t1 = text["sh_addr"], text["sh_addr"] + text["sh_size"]
        rel = {}
        for r in e.get_section_by_name(".rela.dyn").iter_relocations():
            rel[r["r_offset"]] = r["r_addend"]
        nc = ns = 0
        for cls, (a, sz) in sorted(vt.items()):
            for off in range(a + 16, a + sz, 8):
                tgt = rel.get(off)
                if tgt is None:
                    continue
                if not (t0 <= tgt < t1):
                    break
                m = fn.get(tgt, f"FUN_{tgt:x}")
                rows.append((lib, cls, f"{off - a - 16:#x}", m, f"{tgt:x}", "elf:vtable"))
                ns += 1
            nc += 1
        log.info("%s: %d vtables, %d slots", lib, nc, ns)
    with open(OUT, "w") as f:
        f.write("# lib\tclass\toffset\tmethod\ttarget_vaddr\tsource\n")
        f.writelines(keep)
        for r in rows:
            f.write("\t".join(r) + "\n")
    log.info("wrote %d elf rows + %d curated -> %s", len(rows), len(keep), OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
