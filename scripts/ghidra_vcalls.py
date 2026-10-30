#!/usr/bin/env python3
"""Resolve virtual calls in decompiled text through the vtable slots of the index (#169).  Docs: docs/reversing-lessons.md.

  python3 scripts/ghidra_vcalls.py slots <ClassRegex>                 # slot offset -> target per matching class
  python3 scripts/ghidra_vcalls.py who <ClassRegex> <0xOFFSET>        # target of one slot for every matching class
  python3 scripts/ghidra_vcalls.py annotate <decomp.c> [--class C]    # each `(**(code **)(*recv + 0xNN))` with its candidate targets
  python3 scripts/ghidra_vcalls.py abstract <ClassRegex>              # slot offsets whose targets differ between classes = real virtual dispatch

Decompiled offsets equal the vtables.tsv `offset` column (vptr-relative).  Receiver = `param_1`/`this` -> the class named in the file header;
other receivers (globals like cut_le_util: the dynamic class is chosen at run time) -> candidates over the key classes / --class regex.
Needs the index (python3 scripts/ghidra_index.py build).  Values only.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ghidra_index as X  # noqa: E402

KEY = r"^(ASM_RAM_MODEL_YGR_MEAB|ASM_SINGLE_RAM_MODEL_BASE|CUT_ATOM_(CUDA|YGR|CYCLONEII)_LE|CUT_RAM_UTIL\w*|CUT_LE_UTIL\w*)$"
VCALL = re.compile(r"\(\*\*\(code \*\*\)\(\*(?:\(long \*\))?\(?\*?(\w+)\)? \+ 0x([0-9a-f]+)\)\)|\(\*\*\(code \*\*\)\(\*(\w+) \+ 0x([0-9a-f]+)\)\)")


def slots(db, rx):
    return db.execute("select cls, off, target, vaddr from vtslots where cls regexp ? order by cls, off", (rx,)).fetchall()


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__)
        return 2
    db = X.connect()
    if a[0] == "slots":
        for c, off, t, va in slots(db, a[1]):
            print(f"{c}\t+0x{off:x}\t{t}\t0x{va:x}")
    elif a[0] == "who":
        off = int(a[2], 16)
        for c, o, t, va in slots(db, a[1]):
            if o == off:
                print(f"{c}\t{t}\t0x{va:x}")
    elif a[0] == "abstract":
        by = {}
        for c, o, t, va in slots(db, a[1]):
            by.setdefault(o, {})[c] = t
        for o, d in sorted(by.items()):
            ts = set(d.values())
            if len(ts) > 1:
                print(f"+0x{o:x}\t{len(ts)} targets over {len(d)} classes: " + "; ".join(sorted(ts))[:300])
    elif a[0] == "annotate":
        text = open(a[1], errors="replace").read()
        hdr = re.search(r"\n?//// \S+ (\S+?)::(\S+) @", text)
        rx = a[a.index("--class") + 1] if "--class" in a else KEY
        own = hdr.group(1) if hdr else None
        for n, line in enumerate(text.splitlines(), 1):
            for m in VCALL.finditer(line):
                recv = m.group(1) or m.group(3)
                off = int(m.group(2) or m.group(4), 16)
                cls = own if recv in ("param_1", "this") and own else None
                cand = db.execute("select cls, target from vtslots where off=? and cls regexp ?", (off, "^" + cls + "$" if cls else rx)).fetchall()
                tg = sorted({t for _, t in cand})
                print(f"{n}\t{recv}+0x{off:x}\t" + (f"[{cls}] " if cls else f"{len(cand)} classes: ") + "; ".join(tg)[:300])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
