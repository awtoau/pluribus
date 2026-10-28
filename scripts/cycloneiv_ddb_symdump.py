#!/usr/bin/env python3
"""Annotated serializer schemas from Quartus libddb_dygr.so (#141 routing.ddb decode).

Extracts, per operator<</serializer_fn, the sequence of PDB stream ops with the
field-name string each call registers (seg+0x30) - i.e. the exact on-disk schema.
Vtable map (libdb_pdb.so PDB_SEGMENT_READER): see docs/cycloneiv-ddb-format.md.

Usage: python3 scripts/cycloneiv_ddb_symdump.py [symbol-substring ...]
Logs to tmp/logs/cycloneiv_ddb_symdump.log and prints the schemas.
"""
import os, re, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LIB = None
for cand in ("/mnt/2tb/opt/altera", os.path.expanduser("~/opt/altera"), "/opt/altera"):
    import glob
    hits = sorted(glob.glob(os.path.join(cand, "quartus-*/quartus/linux64/libddb_dygr.so")))
    if hits:
        LIB = hits[-1]
        break
if LIB is None:
    sys.exit("libddb_dygr.so not found under any altera install root")

# PDB_SEGMENT_READER vtable (libdb_pdb.so, 25.1std): slot offset -> op name.
VT = {
    0x10: "stl_new", 0x18: "new", 0x20: "new_array", 0x28: "stl_ptr", 0x30: "ptr",
    0x38: "i8_delta", 0x40: "i16_delta", 0x48: "i32_delta", 0x50: "i64_delta(l)",
    0x58: "i64_delta(ul)", 0x60: "i64_delta(q)", 0x68: "stl_string", 0x70: "c_str",
    0x78: "i8", 0x80: "i16", 0x88: "i32", 0x90: "i64", 0x98: "u64", 0xa0: "q64",
    0xa8: "f32", 0xb0: "f64", 0xb8: "bool8", 0xc0: "bool8_v", 0xc8: "enum32",
    0xd0: "field_delta(int,width,prev)", 0xd8: "field_delta(ll,width,prev)",
    0xe0: "serialize_begin", 0xe8: "serialize_end", 0xf0: "stl_begin", 0xf8: "stl_end",
}

def syms():
    out = subprocess.run(["nm", "-C", LIB], capture_output=True, text=True).stdout
    table = {}
    for line in out.splitlines():
        p = line.split(" ", 2)
        if len(p) == 3 and p[0].strip():
            try:
                table.setdefault(int(p[0], 16), p[2]).__class__
            except ValueError:
                pass
            try:
                table.setdefault(int(p[0], 16), p[2])
            except ValueError:
                pass
    return table

def rodata_string(data, vaddr_base, file_base, vaddr):
    off = vaddr - vaddr_base + file_base
    if off < 0 or off >= len(data):
        return None
    end = data.find(b"\0", off, off + 200)
    if end < 0:
        return None
    s = data[off:end]
    try:
        t = s.decode("ascii")
    except UnicodeDecodeError:
        return None
    return t if t and all(32 <= ord(c) < 127 for c in t) else None

def sections():
    out = subprocess.run(["readelf", "-SW", LIB], capture_output=True, text=True).stdout
    secs = {}
    for m in re.finditer(r"\[\s*\d+\]\s+(\S+)\s+\S+\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", out):
        secs[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16))
    return secs

def annotate(name, start, end, data, secs, symtab):
    dis = subprocess.run(
        ["objdump", "-dC", f"--start-address={start:#x}", f"--stop-address={end:#x}", LIB],
        capture_output=True, text=True).stdout
    lines = []
    last_name = {}          # reg -> candidate field-name vaddr
    pending_thunk = None
    for ln in dis.splitlines():
        m = re.search(r"lea\s+0x[0-9a-f]+\(%rip\),%(\w+)\s+#\s+([0-9a-f]+)", ln)
        if m:
            reg, tgt = m.group(1), int(m.group(2), 16)
            s = symtab.get(tgt)
            if s and "thunk" in s:
                pending_thunk = s
            else:
                va, fo, _sz = secs.get(".rodata", (0, 0, 0))
                txt = rodata_string(data, va, fo, tgt)
                if txt:
                    last_name[reg] = txt
            continue
        m = re.search(r"mov\s+0x[0-9a-f]+\(%rip\),%(\w+)\s+#\s+([0-9a-f]+)", ln)
        if m:
            s = symtab.get(int(m.group(2), 16))
            if s and "thunk" in s:
                pending_thunk = s
            continue
        m = re.search(r"call\s+\*0x([0-9a-f]+)\(%r", ln)
        if m:
            slot = int(m.group(1), 16)
            op = VT.get(slot, f"vslot+{slot:#x}")
            nm = last_name.get("rax") or ""
            extra = f"  thunk={pending_thunk}" if pending_thunk and slot in (0x10, 0x18, 0x20, 0x28, 0x30, 0xe0) else ""
            lines.append(f"    {op:<34} {nm}{extra}")
            if slot in (0x10, 0x18, 0x20, 0x28, 0x30, 0xe0):
                pending_thunk = None
            continue
        m = re.search(r"call\s+[0-9a-f]+ <(.+)>", ln)
        if m and ".cold" not in m.group(1) and "@plt" not in m.group(1):
            lines.append(f"    CALL {m.group(1)}")
    return f"== {name} [{start:#x}..{end:#x}]\n" + "\n".join(lines)

def main():
    pats = [p.lower() for p in (sys.argv[1:] or [
        "operator<<", "serializer_fn", "get_route_element_index", "add_route_element"])]
    symtab = syms()
    funcs = sorted((a, n) for a, n in symtab.items())
    data = open(LIB, "rb").read()
    secs = sections()
    out = []
    for i, (addr, nm) in enumerate(funcs):
        if not any(p in nm.lower() for p in pats):
            continue
        if ".cold" in nm:
            continue
        end = funcs[i + 1][0] if i + 1 < len(funcs) else addr + 0x4000
        out.append(annotate(nm, addr, end, data, secs, symtab))
    text = "\n\n".join(out)
    log = os.path.join(REPO, "tmp", "logs", "cycloneiv_ddb_symdump.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "w") as f:
        f.write(f"LIB={LIB}\n\n{text}\n")
    print(text)
    print(f"\n[logged to {log}]", file=sys.stderr)

if __name__ == "__main__":
    main()
