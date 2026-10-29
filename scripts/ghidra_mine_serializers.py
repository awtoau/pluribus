#!/usr/bin/env python3
"""Mine struct layouts from decompiled PDB serializers (`X::operator<<(PDB_SEGMENT_TEMPLATE&)`) into reference/ghidra/structs.tsv.

  python3 scripts/ghidra_mine_serializers.py <lib> <decomp.c> [...]     # log: tmp/logs/ghidra_mine_serializers.log

- Each serializer writes `m_<field>` (name string) and `this + offset` per field: that is a member table with offsets.
- Names stored as DAT_/LAB_ pointers are read from the lib's own file bytes.
- Only names / offsets / coarse types are written.  Rows with source `serializer:*` are regenerated; other rows are kept.
- Decompile text comes from `scripts/ghidra_apply_names.py decomp` or older gitignored analysis dirs (addresses there
  include the Ghidra image base 0x100000; TSV addresses are ELF vaddrs).
"""
import os
import re
import subprocess
import sys

from elftools.elf.elffile import ELFFile

REPO = os.environ.get("PLURIBUS_REPO") or subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
QROOT = os.environ.get("QUARTUS_ROOTDIR", "/mnt/2tb/opt/altera/quartus-25.1/quartus")
OUT = os.path.join(REPO, "reference", "ghidra", "structs.tsv")
LOG = os.path.join(REPO, "tmp", "logs", "ghidra_mine_serializers.log")
IMAGE_BASE = 0x100000
HDR = "# lib\tstruct\tsize\toffset\tfield\ttype\tcomment\tsource\n"
VT_TYPE = {"0x48": "int", "0x40": "ushort", "0xb8": "byte", "0x88": "int", "0x50": "int"}
CASTS = {"string": "std::string", "vector": "std::vector", "deque": "std::deque", "map": "std::map",
         "QTL_BOOL_VECTOR": "QTL_BOOL_VECTOR"}


class Elf:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.segs = [(s["p_vaddr"], s["p_offset"], s["p_filesz"]) for s in ELFFile(self.f).iter_segments() if s["p_type"] == "PT_LOAD"]

    def cstr(self, vaddr):
        for va, off, sz in self.segs:
            if va <= vaddr < va + sz:
                self.f.seek(max(off, off + vaddr - va - 1))
                pre = self.f.read(1) if vaddr - va >= 1 else b"\0"
                b = self.f.read(100)
                if pre != b"\0":              # label sits mid-string: the field name is the next string
                    b = b[b.index(b"\0") + 1:]
                s = b.split(b"\0")[0]
                return s.decode("latin1") if re.fullmatch(rb"m?_?[A-Za-z0-9_]+", s) else None
        return None


def parse(text, elf, lib, src):
    rows = []
    for m in re.finditer(r"^void __thiscall\s+(\w+)::operator<<\((\w+) \*this,PDB_SEGMENT_TEMPLATE \*param_1\)\s*\{(.*?)^\}", text, re.S | re.M):
        cls, body = m.group(1), m.group(3)
        if "(param_1 + 0x30)" not in body:
            continue
        fields = []
        name = fid = None
        for line in body.split("\n"):
            nm = re.search(r'\(param_1 \+ 0x30\) = "(\w+)";', line)
            if nm:
                name = nm.group(1)
            else:
                nm = re.search(r"\(param_1 \+ 0x30\) = &(?:DAT|LAB)_([0-9a-f]+)(?:_\d+)?;", line)
                if nm:
                    name = elf.cstr(int(nm.group(1), 16) - IMAGE_BASE)
            im = re.search(r"\(param_1 \+ 0x10\) = (0x[0-9a-f]+);", line)
            if im:
                fid = int(im.group(1), 16)
            if name is not None and len(name) < 4:
                name = None
            if name is None or "(param_1 + 0x30)" in line or "(param_1 + 0x10)" in line:
                continue
            om = re.search(r"(?:\((\w+) \*\))?\(?\bthis(?: \+ (0x[0-9a-f]+|\d+)|\[(0x[0-9a-f]+)\])?\b", line)
            if not om:
                continue
            off = int(om.group(2) or om.group(3) or "0", 0)
            vt = re.search(r"\*\(long \*\)param_1 \+ (0x[0-9a-f]+)\)\)\(param_1,", line)
            fields.append((off, name, om.group(1), vt.group(1) if vt else None, fid or 0))
            name = fid = None
        if len(fields) < 2:
            continue
        last = {}
        for f in fields:
            last[f[0]] = f           # two names at one offset = a mis-parse; the later name is the one next to that offset
        fields = sorted(last.values(), key=lambda x: x[0])
        if len(fields) < 2:
            continue
        size = 0
        for k, (off, name, cast, vt, fid) in enumerate(fields):
            nxt = fields[k + 1][0] if k + 1 < len(fields) else None
            gap = (nxt - off) if nxt else None
            t = VT_TYPE.get(vt) or ("pointer" if cast == "string" else None)
            width = {"int": 4, "ushort": 2, "byte": 1, "pointer": 8}.get(t)
            if t is None:
                t = f"byte[{gap}]" if gap and gap > 0 else "long"
                width = gap or 8
            elif gap and gap >= 16 and gap % width == 0 and t != "pointer":
                t = f"{t}[{gap // width}]"
                width = gap
            size = max(size, off + (width or 8))
            cm = f"serializer field id 0x{fid:x}" + (f"; C++ {CASTS[cast]}" if cast in CASTS else "")
            fields[k] = (off, name, t, cm)
        # serializer address = ELF vaddr of the first line "//// X::operator<< @ addr" not tracked here; keep lib-level source
        size = (size + 7) & ~7
        for off, name, t, cm in fields:
            rows.append((lib, cls, size, f"0x{off:x}", name, t, cm, f"serializer:{src}"))
    return rows


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    lib = sys.argv[1]
    elf = Elf(os.path.join(QROOT, "linux64", lib + ".so"))
    new = []
    for p in sys.argv[2:]:
        new += parse(open(p, errors="replace").read(), elf, lib, os.path.basename(p))
    # a class can appear in several decompile files / twice per file (thunk + body): keep the richest set
    best = {}
    for r in new:
        best.setdefault((r[0], r[1]), []).append(r)
    keep = []
    seen = {}
    for (l, c), rs in best.items():
        by_src = {}
        for r in rs:
            by_src.setdefault(r[7], []).append(r)
        keep += max(by_src.values(), key=len)
    keep_keys = {(r[0], r[1]) for r in keep}
    old = []
    if os.path.exists(OUT):
        for line in open(OUT):
            if line.startswith("#") or not line.strip():
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) >= 8 and c[7].startswith("serializer:") and (c[0], c[1]) in keep_keys:
                continue          # regenerated below
            old.append(c)
    rows = old + [list(map(str, r)) for r in keep]
    rows.sort(key=lambda c: (c[0], c[1], int(c[3], 0) if c[3] else -1))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(HDR)
        for c in rows:
            f.write("\t".join(c) + "\n")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    msg = f"{lib}: {len(keep)} fields in {len(keep_keys)} structs; file total {len(rows)} rows"
    open(LOG, "a").write(msg + "\n")
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
