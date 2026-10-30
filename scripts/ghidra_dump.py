#!/usr/bin/env python3
"""Dump tables / struct arrays from the vendor libs' relocated data, no Ghidra needed (#169).  Docs: docs/reversing-lessons.md.

  python3 scripts/ghidra_dump.py dump-table <lib> <symbol-regex|0xVADDR> <type> [count]
        type = u8 u16 u32 u64 i32 i64 ptr cstr (ptr = resolved pointer: symbol / string / data+off); count default = symbol size / width
  python3 scripts/ghidra_dump.py dump-struct-array <lib> <struct> <0xVADDR|symbol> <count>     # layout from reference/ghidra/structs.tsv
  python3 scripts/ghidra_dump.py dump-struct-array <lib> --layout "0:ptr,8:u32,12:i32" --stride 16 <0xVADDR|symbol> <count>
  python3 scripts/ghidra_dump.py ctor-tables <lib> <Class>      # data tables a class's constructors reference (lea rip) dumped as ptr/u32 words
  python3 scripts/ghidra_dump.py switch <lib> <0xTABLE_VADDR> <count> [first-case]   # jump table the decompiler could not recover: case -> target (+ enclosing symbol)
  python3 scripts/ghidra_dump.py emulate <lib> <0xVADDR> <maxSteps> <arg|A..B> ...    # harness: sweep -> table (Ghidra P-code, snapshot)

Pointers: .rela.dyn R_X86_64_RELATIVE addends / 64-bit symbol relocations are resolved as scripts/cycloneiv_clean_dirt.py does.
Output is values only (names, numbers); keep dumps of vendor data under vendor-analysis/ or tmp/, not in tracked files.
"""
import bisect
import os
import re
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(HERE)
QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
TSV = os.path.join(REPO, "reference", "ghidra")
WIDTH = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "i32": 4, "i64": 8, "ptr": 8}
FMT = {"u8": "<B", "u16": "<H", "u32": "<I", "u64": "<Q", "i32": "<i", "i64": "<q"}
CTYPE = {"byte": "u8", "bool": "u8", "char": "u8", "short": "u16", "ushort": "u16", "int": "i32", "uint": "u32", "long": "i64", "pointer": "ptr",
         "undefined4": "u32", "undefined8": "u64", "longlong": "i64"}


class Lib:
    def __init__(self, name):
        p = os.path.join(QROOT, "linux64", name + ".so")
        if not os.path.exists(p):
            p = os.path.join(QROOT, "linux64", name)
        self.name = name
        self.elf = ELFFile(open(p, "rb"))
        self.secs = [(s["sh_addr"], s["sh_size"], s.data(), s.name) for s in self.elf.iter_sections()
                     if s["sh_addr"] and s["sh_type"] == "SHT_PROGBITS" and s.name not in (".text", ".plt", ".plt.got", ".init", ".fini")]
        self.rel = {}                    # offset -> (addend|None, symbol name|None)
        dyn = self.elf.get_section_by_name(".dynsym")
        for rs in self.elf.iter_sections():
            if rs["sh_type"] != "SHT_RELA":
                continue
            syms = self.elf.get_section(rs["sh_link"]) if rs["sh_link"] else dyn
            for r in rs.iter_relocations():
                t = r["r_info_type"]
                if t == 8:       # R_X86_64_RELATIVE
                    self.rel[r["r_offset"]] = (r["r_addend"], None)
                elif t in (1, 6) and r["r_info_sym"] and syms is not None:    # R_X86_64_64 / GLOB_DAT
                    s = syms.get_symbol(r["r_info_sym"])
                    self.rel[r["r_offset"]] = ((s["st_value"] + r["r_addend"]) if s["st_value"] else None, s.name)
        self.syms = []
        for sn in (".symtab", ".dynsym"):
            st = self.elf.get_section_by_name(sn)
            if st is None:
                continue
            for s in st.iter_symbols():
                if s["st_value"] and s.name and s["st_info"]["type"] in ("STT_FUNC", "STT_OBJECT", "STT_NOTYPE"):
                    self.syms.append((s["st_value"], s["st_size"], s.name, s["st_info"]["type"]))
        self.syms.sort()
        self.addrs = [s[0] for s in self.syms]

    def read(self, addr, n):
        for a, sz, d, _ in self.secs:
            if a <= addr and addr + n <= a + sz:
                return d[addr - a:addr - a + n]
        return None

    def demangle(self, names):
        if not names:
            return {}
        r = subprocess.run(["c++filt"], input="\n".join(names), capture_output=True, text=True)
        return dict(zip(names, r.stdout.split("\n")))

    def sym_at(self, addr):
        i = bisect.bisect_right(self.addrs, addr) - 1
        while i >= 0:
            a, sz, n, t = self.syms[i]
            if a <= addr < a + max(sz, 1) or (t == "STT_FUNC" and a == addr):
                return n, addr - a
            if addr - a > 0x10000:
                break
            i -= 1
        return None

    def cstr(self, addr, lim=120):
        for a, sz, d, nm in self.secs:
            if a <= addr < a + sz and nm in (".rodata", ".data", ".data.rel.ro", ".rodata.str1.1", ".rodata.str1.8"):
                e = d.find(b"\0", addr - a, addr - a + lim)
                if e >= addr - a:
                    b = d[addr - a:e]
                    if all(32 <= c < 127 for c in b):
                        return b.decode()
        return None

    def ptr(self, off):
        """pointer stored at `off`: relocation target if relocated, else raw value; -> text"""
        r = self.rel.get(off)
        if r is not None:
            tgt, nm = r
            if tgt is None:
                return f"ext:{nm}"
            return self.describe(tgt)
        raw = self.read(off, 8)
        v = struct.unpack("<Q", raw)[0] if raw else 0
        return "0" if v == 0 else f"raw:{v:#x}"

    def describe(self, tgt):
        s = self.cstr(tgt)
        sym = self.sym_at(tgt)
        if sym and sym[0].startswith("_Z"):
            sym = (self.demangle([sym[0]])[sym[0]], sym[1])
        if s is not None and not (sym and sym[1] == 0 and not sym[0].startswith(".")):
            return f'"{s}"'
        if sym:
            return f"{sym[0]}+{sym[1]:#x}" if sym[1] else sym[0]
        return f"{tgt:#x}"

    def find_sym(self, pat):
        out = []
        rx = re.compile(pat)
        names = [s for s in self.syms if rx.search(s[2])]
        dm = self.demangle([s[2] for s in names])
        for s in self.syms:
            if s in names and (rx.search(s[2]) or rx.search(dm.get(s[2], ""))):
                out.append(s)
        if not out:           # try demangled names
            allm = self.demangle([s[2] for s in self.syms if s[2].startswith("_Z")])
            out = [s for s in self.syms if rx.search(allm.get(s[2], s[2]))]
        return out


def resolve_addr(L, spec):
    if re.fullmatch(r"0x[0-9a-fA-F]+", spec):
        return int(spec, 16), 0, spec
    c = L.find_sym(spec)
    if not c:
        sys.exit(f"{spec}: no symbol in {L.name}")
    a, sz, n, _ = c[0]
    return a, sz, n


def dump_table(L, spec, typ, count=None):
    a, sz, name = resolve_addr(L, spec)
    w = WIDTH.get(typ, 1 if typ == "cstr" else None)
    n = count if count is not None else (sz // w if sz and w else 16)
    print(f"# {L.name} {name} @ {a:#x} type={typ} count={n}")
    rows = []
    for i in range(n):
        off = a + i * w
        if typ == "ptr":
            rows.append((i, L.ptr(off)))
        elif typ == "cstr":
            p = L.ptr(a + i * 8)
            rows.append((i, p))
        else:
            b = L.read(off, w)
            if b is None:
                break
            rows.append((i, struct.unpack(FMT[typ], b)[0]))
    for i, v in rows:
        print(f"{i}\t{a + i * w:#x}\t{v if isinstance(v, str) else (hex(v) if v >= 0 else v)}")
    return rows


def struct_layout(lib, sname):
    fields, size = [], 0
    for line in open(os.path.join(TSV, "structs.tsv")):
        c = line.rstrip("\n").split("\t")
        if line.startswith("#") or len(c) < 8 or c[1] != sname:
            continue
        if lib and c[0] != lib and c[0] != "*":
            continue
        size = int(c[2], 0)
        t = c[5].strip()
        m = re.match(r"(\w+)\[(\d+)\]", t)
        fields.append((int(c[3], 0), c[4], "bytes" if m and m.group(1) in ("byte", "undefined") else CTYPE.get(t, t), int(m.group(2)) if m else 0))
    seen, out = set(), []
    for f in sorted(fields):
        if f[0] not in seen:
            seen.add(f[0])
            out.append(f if f[2] in FMT or f[2] in ("ptr", "bytes") else (f[0], f[1], "i32", 0))   # enum-typed field = 4-byte int
    return out, size


def dump_struct_array(L, args):
    layout = stride = None
    if args[0] == "--layout":
        layout = [(int(x.split(":")[0], 0), x.split(":")[0], x.split(":")[1], 0) for x in args[1].split(",")]
        stride = int(args[3], 0)
        args = args[4:]
        sname = "layout"
    else:
        sname, args = args[0], args[1:]
        layout, stride = struct_layout(L.name, sname)
        if not layout:
            sys.exit(f"struct {sname}: not in reference/ghidra/structs.tsv for {L.name}")
    a, _, name = resolve_addr(L, args[0])
    count = int(args[1], 0)
    print(f"# {L.name} {sname}[{count}] @ {a:#x} stride={stride}")
    for i in range(count):
        base = a + i * stride
        cells = []
        for off, fn, ty, ln in layout:
            if ty == "ptr":
                v = L.ptr(base + off)
            elif ty == "bytes":
                b = L.read(base + off, ln)
                v = b.hex() if b else "?"
            elif ty in FMT:
                b = L.read(base + off, WIDTH[ty])
                v = hex(struct.unpack(FMT[ty], b)[0]) if b else "?"
            else:
                v = f"?{ty}"
            cells.append(f"{fn}={v}")
        print(f"[{i}] {base:#x}\t" + "\t".join(cells))


def ctor_tables(L, cls, maxwords=48):
    """Data blocks a class's constructors point at (lea disp(%rip)) -> word dump; skips vtables/typeinfo and code."""
    rx = re.compile(r"(^|::)" + re.escape(cls) + r"::" + re.escape(cls.rsplit("::", 1)[-1]) + r"\(")
    allm = L.demangle([s[2] for s in L.syms if s[2].startswith("_Z")])
    ctors = {}
    for a, sz, n, t in L.syms:
        d = allm.get(n, n)
        if t == "STT_FUNC" and rx.search(d) and sz:
            ctors[a] = (sz, d)
    seen = set()
    for a, (sz, d) in sorted(ctors.items()):
        print(f"# ctor {d} @ {a:#x} size {sz}")
        out = subprocess.run(["objdump", "-d", "--no-show-raw-insn", f"--start-address={a:#x}", f"--stop-address={a + sz:#x}",
                              os.path.join(QROOT, "linux64", L.name + ".so")], capture_output=True, text=True).stdout
        for m in re.finditer(r"lea\s+[-0-9a-fx]+\(%rip\),%\w+\s+#\s+([0-9a-f]+)", out):
            t = int(m.group(1), 16)
            if t in seen or L.read(t, 8) is None:
                continue
            sym = L.sym_at(t)
            nm = sym[0] if sym else ""
            if nm.startswith("_ZTV") or nm.startswith("_ZTI") or nm.startswith("_ZTS"):
                continue
            seen.add(t)
            print(f"## table {t:#x} {nm}+{sym[1] if sym else 0:#x}")
            row = []
            for k in range(maxwords * 2):
                off = t + 4 * k
                b = L.read(off, 4)
                if b is None:
                    break
                if off in L.rel:
                    row.append(L.ptr(off))
                elif off - 4 in L.rel:
                    continue
                else:
                    row.append(f"{struct.unpack('<I', b)[0]:#x}")
                if len(row) == 6:
                    print(f"  +{4 * (k - len(row) + 1):#x}\t" + " ".join(row))
                    row = []
            if row:
                print(f"  +{4 * (k - len(row) + 1):#x}\t" + " ".join(row))


def switch_table(L, table, count, first=0):
    """gcc x86-64 PIC jump table: int32 entries, target = table + entry.  Prints case, target vaddr, symbol."""
    print(f"# {L.name} switch table {table:#x}, {count} entries, first case {first}")
    for i in range(count):
        b = L.read(table + 4 * i, 4)
        if b is None:
            break
        tgt = (table + struct.unpack("<i", b)[0]) & 0xFFFFFFFFFFFFFFFF
        sym = L.sym_at(tgt)
        nm = L.demangle([sym[0]])[sym[0]] if sym and sym[0].startswith("_Z") else (sym[0] if sym else "")
        print(f"{first + i}\t{tgt:#x}\t{nm}+{sym[1]:#x}" if sym else f"{first + i}\t{tgt:#x}")


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__)
        return 2
    cmd, lib, rest = a[0], a[1], a[2:]
    if cmd == "emulate":     # harness: sweep -> table; prints inputs -> rax with the status histogram (ok / steps / fault:call = not a leaf function)
        r = subprocess.run([sys.executable, os.path.join(HERE, "ghidra_apply_names.py"), "emulate", lib] + rest)
        t = os.path.join(REPO, "vendor-analysis", "altera", "analysis", "readable", f"emulate_{lib}_{rest[0]}.tsv")
        if r.returncode == 0 and os.path.exists(t):
            rows = [l.rstrip("\n").split("\t") for l in open(t)]
            hist = {}
            for c in rows:
                hist[c[-1]] = hist.get(c[-1], 0) + 1
            print(f"# {len(rows)} runs, status {hist}; columns: lib vaddr args... rax status ({t})")
            for c in rows[:int(os.environ.get('EMU_SHOW', '60'))]:
                print("\t".join(c[2:]))
        return r.returncode
    L = Lib(lib)
    if cmd == "dump-table":
        dump_table(L, rest[0], rest[1], int(rest[2], 0) if len(rest) > 2 else None)
    elif cmd == "dump-struct-array":
        dump_struct_array(L, rest)
    elif cmd == "switch":
        switch_table(L, int(rest[0], 16), int(rest[1], 0), int(rest[2], 0) if len(rest) > 2 else 0)
    elif cmd == "ctor-tables":
        ctor_tables(L, rest[0])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
