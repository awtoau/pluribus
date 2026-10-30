#!/usr/bin/env python3
"""Bind ASM_* classes to asmdb arch group type enums: parse the `ASM_ASMDBIO::search_for_*_arch_groups` factories (#169).

  python3.15t scripts/cycloneiv_clean_class_bind.py     # -> lifters/cycloneiv_clean/class_groups_table.json, log tmp/logs/cycloneiv_clean_class_bind.log

Each factory switches on `group->type` (this+0xc, ASMDB_ARCH_GROUP_TYPE) and `new`s the processing class (vtable store).  The switch is
read straight from the lib's machine code (objdump -d of libcomp_asm.so, vendor install; static): jump tables (cmp/ja, optional sub K,
lea table, movslq) and single `cmp $imm,%eax; je/jne` cases; a case's class = the first `vtable for ASM_X` / `ASM_X::ASM_X(` of its block.
Every row's `source` = factory@vaddr + case value.  Enum value -> name: libdb_asmdb arch-group-type table.
"""
import json
import logging
import os
import re
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import toolchain  # noqa: E402
import cycloneiv_clean_dirt as D  # noqa: E402

QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
AN = os.path.join(REPO, "vendor-analysis", "altera", "analysis")
OUT = os.path.join(REPO, "lifters", "cycloneiv_clean", "class_groups_table.json")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_class_bind.log")
INS = re.compile(r"^\s*([0-9a-f]+):\s+(\S+)\s*(.*)$")
HDR = re.compile(r"^([0-9a-f]+) <(.*)>:$")
CLS = re.compile(r"vtable for (ASM\w*?_\w+)\+0x10|<(ASM\w*?_\w+)::\2\(")
ST = re.compile(r"mov[lbwq]\s+\$(0x[0-9a-f]+),(0x[0-9a-f]+)\(%r\w+\)")
LIBS = (("libcomp_asm", "nm_full_comp_asm.txt"), ("libcomp_asmgx", "nm_comp_asmgx.txt"), ("libcomp_asmcc", "nm_comp_asmcc.txt"))
FACT = r"(ASM_ASMDBIO::search_for_\w+_arch_groups|asm_search_for_\w+_arch_groups|asmgx_search_for_arch_groups|asmcc_search_for_\w+_arch_groups)"


def factories(nmfile):
    out = []
    for line in open(os.path.join(AN, nmfile), errors="replace"):
        m = re.match(r"^([0-9a-f]+) [tT] " + FACT + r"\(", line)
        if m:
            out.append((int(m.group(1), 16), m.group(2)))
    return sorted(out)


def parse_function(lines, start_idx):
    """list of (addr, mnem, ops, raw) until the next function header."""
    ins = []
    i = start_idx + 1
    while i < len(lines) and not HDR.match(lines[i]):
        m = INS.match(lines[i])
        if m:
            ins.append((int(m.group(1), 16), m.group(2), m.group(3), lines[i]))
        i += 1
    return ins


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    lg = logging.getLogger("bind")
    lg.setLevel(logging.INFO)
    lg.addHandler(logging.FileHandler(LOG, "w"))
    lg.addHandler(logging.StreamHandler(sys.stdout))
    rows = []
    gname = D.enum_tables()["arch_group_type"]
    for LIB, nmfile in LIBS:
        rows += bind_lib(lg, LIB, nmfile, gname)
    json.dump(rows, open(OUT, "w"), indent=1)
    ok = sum(1 for r in rows if r["group"] and (r["cls"][4:] == r["group"] or r["cls"][4:].endswith(r["group"]) or r["group"].endswith(r["cls"][4:])))
    lg.info("bound rows %d, distinct classes %d, class-name == group-name rows %d", len(rows), len({r["cls"] for r in rows}), ok)
    for r in rows:
        if r["cls"] in ("ASM_IO_USE_BUS_HOLD", "ASM_LE_USE_CARRY", "ASM_OPTION_REG_USE_NCEO"):
            lg.info("check %s", r)
    return 0


def bind_lib(lg, LIB, nmfile, gname):
    lib = os.path.join(QROOT, "linux64", LIB + ".so")
    asm = subprocess.run(["objdump", "-d", "--no-show-raw-insn", "-C", lib], capture_output=True, text=True, check=True).stdout.split("\n")
    pos = {}
    for i, l in enumerate(asm):
        m = HDR.match(l)
        if m:
            pos.setdefault(int(m.group(1), 16), i)
    e = ELFFile(open(lib, "rb"))
    ro = e.get_section_by_name(".rodata")
    rows = []
    for addr, fname in factories(nmfile):
        ins = parse_function(asm, pos[addr])
        idx = {a: k for k, (a, _, _, _) in enumerate(ins)}
        cases = {}                                    # target addr -> [case values]

        def add(v, t):
            cases.setdefault(t, set()).add(v)

        for k, (a, mn, ops, raw) in enumerate(ins):
            if mn == "cmp" and re.match(r"\$0x[0-9a-f]+,%eax$", ops) and k + 1 < len(ins):
                v = int(ops.split(",")[0][1:], 16)
                nm, no = ins[k + 1][1], ins[k + 1][2]
                if nm == "je":
                    add(v, int(no.split()[0], 16))
                elif nm == "jne" and k + 2 < len(ins):
                    add(v, ins[k + 2][0])
            if mn == "movslq" and re.match(r"\(%r\w+,%rax,4\),%rax$", ops):
                # table address: the lea just before (comment `# ADDR`), K from a `sub $K,%eax` before, N from `cmp $N,%eax`
                t = None
                for b in range(k - 1, max(k - 4, 0), -1):
                    m = re.search(r"# ([0-9a-f]+) ", ins[b][3])
                    if ins[b][1] == "lea" and m:
                        t = int(m.group(1), 16)
                        break
                if t is None:
                    continue
                K, N = 0, None
                for b in range(k - 1, max(k - 14, 0), -1):
                    m = re.match(r"\$(0x[0-9a-f]+),%eax$", ins[b][2])
                    if m and ins[b][1] == "sub" and not K:
                        K = int(m.group(1), 16)
                    if m and ins[b][1] == "cmp" and N is None:
                        N = int(m.group(1), 16)
                if N is None:
                    continue
                for j in range(N + 1):
                    off = t - ro["sh_addr"] + 4 * j
                    rel = struct.unpack_from("<i", ro.data(), off)[0]
                    add(K + j, t + rel)
        n = 0
        for t, vals in cases.items():
            if t not in idx:
                continue
            cls, stores = None, {}
            for a, mn, ops, raw in ins[idx[t]:idx[t] + 60]:
                m = CLS.search(raw)
                if m and not cls:
                    cls = m.group(1) or m.group(2)
                m = ST.search(f"{mn} {ops}")
                if m and int(m.group(2), 16) >= 0x10:       # fields after the vptr / group ptr; 0x10, 0x14 are the base's zero init
                    stores[m.group(2)] = int(m.group(1), 16)
                if mn in ("jmp", "ret"):
                    break
            if cls:
                for v in sorted(vals):
                    rows.append(dict(enum=v, group=gname.get(v), cls=cls, lib=LIB, factory=fname, init=stores, source=f"{LIB}:{fname}@{addr:#x} case {v:#x}"))
                    n += 1
        lg.info("%-70s cases %4d bound %4d", fname, sum(len(v) for v in cases.values()), n)
    return rows

if __name__ == "__main__":
    sys.exit(main())
