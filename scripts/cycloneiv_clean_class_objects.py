#!/usr/bin/env python3
"""Vtable / class-instance recovery for the ASM_* hierarchy: static object -> class -> fields, read from the relocated .data (#169).

  python3 scripts/cycloneiv_clean_class_objects.py <lib> [--dump CLASS]     # log tmp/logs/cycloneiv_clean_class_objects.log

- vtable symbols = `nm` dumps (`vtable for X`); an object of class X is a .data slot whose R_X86_64_RELATIVE addend = vtable + 16.
- Prints per class the slot addresses and the following 5 qwords (raw), so a constructor-less class (fields set by static init) can be read directly.
"""
import collections
import logging
import os
import re
import struct
import sys

from elftools.elf.elffile import ELFFile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
AN = os.path.join(REPO, "vendor-analysis", "altera", "analysis")
NM = {"libcomp_asm": "nm_full_comp_asm.txt", "libcomp_asm2": "nm_full_comp_asm2.txt", "libcomp_asmgx": "nm_comp_asmgx.txt", "libcomp_asmcc": "nm_comp_asmcc.txt"}


def objects(lib):
    vt = {}
    for line in open(os.path.join(AN, NM[lib]), errors="replace"):
        m = re.match(r"^([0-9a-f]+) [dD] vtable for (\S+)$", line.strip())
        if m:
            vt[int(m.group(1), 16) + 16] = m.group(2)
    e = ELFFile(open(os.path.join(QROOT, "linux64", lib + ".so"), "rb"))
    secs = [(s["sh_addr"], s["sh_addr"] + s["sh_size"], s) for s in e.iter_sections() if s["sh_addr"] and s["sh_type"] == "SHT_PROGBITS"]

    def read(addr, n):
        for lo, hi, s in secs:
            if lo <= addr and addr + n <= hi:
                return s.data()[addr - lo:addr - lo + n]
        return None

    out = collections.defaultdict(list)
    for r in e.get_section_by_name(".rela.dyn").iter_relocations():
        c = vt.get(r["r_addend"])
        if c:
            raw = read(r["r_offset"], 48)
            out[c].append((r["r_offset"], struct.unpack("<6Q", raw) if raw and len(raw) == 48 else None))
    return out


def main():
    lib = sys.argv[1]
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    lg = logging.getLogger("co")
    lg.setLevel(logging.INFO)
    lg.addHandler(logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_class_objects.log"), "w"))
    lg.addHandler(logging.StreamHandler(sys.stdout))
    o = objects(lib)
    lg.info("%s: %d classes with vtable, %d with a static instance", lib, sum(1 for _ in o) , len(o))
    pick = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--dump" else None
    for c, lst in sorted(o.items()):
        if pick and c != pick:
            continue
        for a, q in lst[:3]:
            lg.info("%s @%#x %s", c, a, q and " ".join(f"{x:#x}" for x in q))
    return 0


if __name__ == "__main__":
    sys.exit(main())
