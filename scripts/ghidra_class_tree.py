#!/usr/bin/env python3
"""C++ class tree of a Quartus lib from its RTTI typeinfo objects (names only).  (#165, #168)

  python3 scripts/ghidra_class_tree.py <lib> [...]     # -> vendor-analysis/altera/analysis/readable/class_tree.tsv
Columns: lib, class, kind (si|vmi|base), bases (comma list), vtable_slots (from reference/ghidra/vtables.tsv).
Itanium ABI: __class_type_info {vptr,name}; __si_class_type_info + base ptr; __vmi_class_type_info + flags,count,{ptr,offset_flags}[].
"""
import os
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(HERE)
QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
OUT = os.path.join(REPO, "vendor-analysis", "altera", "analysis", "readable", "class_tree.tsv")
VT = os.path.join(REPO, "reference", "ghidra", "vtables.tsv")


def tree(lib):
    path = os.path.join(QROOT, "linux64", lib + ".so")
    nm = subprocess.run(["nm", "-C", "-S", path], capture_output=True, text=True, check=True).stdout
    ti = {}
    for ln in nm.splitlines():
        p = ln.split(None, 3)
        if len(p) == 4 and p[3].startswith("typeinfo for "):
            ti[int(p[0], 16)] = (p[3][13:], int(p[1], 16))
    e = ELFFile(open(path, "rb"))
    rel = {r["r_offset"]: r["r_addend"] for r in e.get_section_by_name(".rela.dyn").iter_relocations()}
    dyn = e.get_section_by_name(".dynsym")
    ext = {}
    for r in e.get_section_by_name(".rela.dyn").iter_relocations():
        if r["r_info_sym"]:
            nm_ = dyn.get_symbol(r["r_info_sym"]).name
            if nm_.startswith("_ZTI"):
                ext[r["r_offset"]] = nm_
    dem = {}
    if ext:
        names = sorted(set(ext.values()))
        res = subprocess.run(["c++filt"], input="\n".join(names), capture_output=True, text=True).stdout.splitlines()
        dem = {n: d.replace("typeinfo for ", "") for n, d in zip(names, res)}
    sections = [s for s in e.iter_sections() if s["sh_addr"] and s["sh_type"] == "SHT_PROGBITS"]

    def u32(a):
        for s in sections:
            if s["sh_addr"] <= a < s["sh_addr"] + s["sh_size"]:
                return struct.unpack_from("<I", s.data(), a - s["sh_addr"])[0]
        return 0
    out = []
    for a, (name, size) in sorted(ti.items(), key=lambda x: x[1][0]):
        bases, kind = [], "base"
        if size == 24 and ((a + 16) in rel or (a + 16) in ext):
            kind = "si"
            b = ti.get(rel[a + 16]) if (a + 16) in rel else None
            bases = [b[0]] if b else ([dem[ext[a + 16]]] if (a + 16) in ext else [])
        elif size > 24:
            kind = "vmi"
            n = u32(a + 20)
            for i in range(n):
                o = a + 24 + 16 * i
                b = ti.get(rel.get(o))
                if b:
                    bases.append(b[0])
                elif o in ext:
                    bases.append(dem[ext[o]])
        out.append((lib, name, kind, ",".join(bases)))
    return out


def main():
    libs = sys.argv[1:]
    if not libs:
        print(__doc__)
        return 2
    slots = {}
    if os.path.exists(VT):
        for ln in open(VT):
            c = ln.rstrip("\n").split("\t")
            if len(c) >= 6 and not ln.startswith("#"):
                slots[(c[0], c[1])] = slots.get((c[0], c[1]), 0) + 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    rows = []
    for lib in libs:
        rows += tree(lib)
    with open(OUT, "w") as f:
        f.write("# lib\tclass\tkind\tbases\tvtable_slots\n")
        for r in rows:
            f.write("\t".join(r) + f"\t{slots.get((r[0], r[1]), 0)}\n")
    print(f"{len(rows)} classes -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
