#!/usr/bin/env python3
"""Decode the asmdb dirt ddb (PDB pool order, #168) and the asmdb enum-name tables from vendor files.

  python3 scripts/cycloneiv_clean_dirt.py [dirt.ddb ...]     # log: tmp/logs/cycloneiv_clean_dirt.log

- Pool order (libdb_pdb PDB_SEGMENT_READER::xfr_ptr / finish_reading_all, docs/ghidra-workflow.md): objects are serialized
  in creation order of the pointer tags; for the dirt tree one global FIFO of tags reproduces every file exactly.
- ASMDB_DIRT object = m_index (i32 delta vs the previous object of the pool), m_has_dirt_type (byte); INNER adds
  vector<DIRT*> (u32 count + tags), INTEGER vector<int> (count + i32 deltas, running sum), STRING vector<string>.
- Enum names: libdb_asmdb ASMDB_TRANSLATOR::m_asmdb_{dirt_type,arch_group_type,arch_group_block_type}_debug_string_table
  (char* arrays, pointers are .rela.dyn RELATIVE addends).  Table symbol offsets: reference/ghidra/globals.tsv.
"""
import glob
import logging
import os
import struct
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cyclonev_ddb_decode as dd  # noqa: E402
from elftools.elf.elffile import ELFFile  # noqa: E402

QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR", "/mnt/2tb/opt/altera/quartus-25.1/quartus")
TABLES = {"dirt_type": (0xEB020, 0x980), "arch_group_type": (0xEC320, 0x91C0), "block_type": (0xFE6A0, 0x10F8)}
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_dirt.log")


def enum_tables():
    e = ELFFile(open(os.path.join(QROOT, "linux64", "libdb_asmdb.so"), "rb"))
    ro = e.get_section_by_name(".rodata")
    data, base = ro.data(), ro["sh_addr"]
    rel = [(r["r_offset"], r["r_addend"]) for r in e.get_section_by_name(".rela.dyn").iter_relocations()]
    out = {}
    for name, (sym, size) in TABLES.items():
        t = {}
        for off, add in rel:
            if sym <= off < sym + size:
                a = add - base
                t[(off - sym) // 8] = data[a:data.index(0, a)].decode()
        out[name] = t
    return out


def decode_dirt(path):
    """-> (nodes, consumed_all).  node = dict(cls 2 inner / 3 integer / 4 string, idx, flag, kids|val); children in FIFO order."""
    b = b"".join(dd.iter_body(path))
    pos = 0

    def u32():
        nonlocal pos
        pos += 4
        return struct.unpack_from("<I", b, pos - 4)[0]

    def i32():
        nonlocal pos
        pos += 4
        return struct.unpack_from("<i", b, pos - 4)[0]

    q, nodes, acc = deque([u32()]), [], 0
    while q:
        c = q.popleft() >> 2
        acc += i32()
        flag = b[pos]
        pos += 1
        n = {"cls": c, "idx": acc, "flag": flag}
        if c == 2:
            ch = [u32() for _ in range(u32())]
            n["kids"] = len(ch)
            q.extend(ch)
        elif c == 3:
            a, v = 0, []
            for _ in range(u32()):
                a += i32()
                v.append(a)
            n["val"] = v
        elif c == 4:
            v = []
            for _ in range(u32()):
                m = u32()
                v.append(b[pos:pos + m].decode())
                pos += m
            n["val"] = v
        else:
            raise ValueError(f"unknown class {c} at {pos}")
        nodes.append(n)
    nxt = 1
    for n in nodes:
        if n["cls"] == 2:
            n["ch"] = list(range(nxt, nxt + n["kids"]))
            nxt += n["kids"]
    return nodes, pos == len(b)


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = logging.getLogger("dirt")
    log.addHandler(logging.FileHandler(LOG))
    log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(QROOT, "common", "devinfo", "cyclone*", "*dirt.ddb")))
    tabs = enum_tables()
    log.info("enum tables: %s", {k: len(v) for k, v in tabs.items()})
    for p in paths:
        nodes, ok = decode_dirt(p)
        types = sum(1 for n in nodes if n["flag"] == 1 and n["cls"] == 2)
        log.info("%s: %d nodes, all bytes consumed=%s, typed inner nodes %d", os.path.basename(p), len(nodes), ok, types)
    return 0


if __name__ == "__main__":
    sys.exit(main())
