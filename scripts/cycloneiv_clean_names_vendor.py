#!/usr/bin/env python3
"""Generate lifters/cycloneiv_clean/names_table.json straight from vendor files (#165).  No search, no hash decode.

  python3 scripts/cycloneiv_clean_names_vendor.py      # log: tmp/logs/cycloneiv_clean_names_vendor.log

Sources:
  - libddb_dstr.so  DSTR_TRANSLATOR::m_dev_element_enum_debug_string_table: char*[2716], index = DEV_ELEMENT_ENUM
    (pointers via .rela.dyn R_X86_64_RELATIVE addends into .rodata).
  - ddb_stingray4_hdr.ddb body: one record per element; first string = debug name (-> enum above), later strings =
    description + aliases; the last non-.dxf string is the RCF type name (R4 = H4, C4 = V4, LOCAL_INTERCONNECT = LAB_LINE ...).
  - hdr_int of the name table is not used (not needed).
Comparison oracle only: tmp/logs/cycloneiv_clean_names_search.json (routing-tree edge consistency); never feeds the table.
"""
import json
import os
import re
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_ddb_decode as dd  # noqa: E402
from elftools.elf.elffile import ELFFile  # noqa: E402

QROOT = os.path.dirname(os.path.dirname(dd.DEVINFO))
HDR = os.path.join(dd.DEVINFO, "cycloneivgx", "ddb_stingray4_hdr.ddb")
DSTR = os.path.join(QROOT, "linux64", "libddb_dstr.so")
SYM_ADDR, SYM_SIZE = 0x477980, 0x54E0   # nm -D: m_dev_element_enum_debug_string_table (D, size 0x54e0)
SEARCH = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_names_search.json")
OUT = os.path.join(REPO, "lifters", "cycloneiv_clean", "names_table.json")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_names_vendor.log")
NAME_TABLE = (23440, 28816)   # hdr body span of the name:int table (same span as names_table.py history)
TAIL = 28816                  # first byte after the name table: [0:i32][6][6 enums][148][148 enums]...

_log = []


def say(s):
    print(s)
    _log.append(s)


def enum_debug_names():
    """enum -> debug string, from libddb_dstr.so."""
    e = ELFFile(open(DSTR, "rb"))
    ro = e.get_section_by_name(".rodata")
    data, base = ro.data(), ro["sh_addr"]
    out = {}
    for r in e.get_section_by_name(".rela.dyn").iter_relocations():
        o = r["r_offset"]
        if SYM_ADDR <= o < SYM_ADDR + SYM_SIZE:
            a = r["r_addend"] - base
            out[(o - SYM_ADDR) // 8] = data[a:data.index(0, a)].decode()
    assert len(out) == SYM_SIZE // 8, len(out)
    return out


def tokens(body, p, maxn=14):
    """Length-prefixed strings from p; len 0 = empty.  Stops at a non-string or 5 empties in a row."""
    out, empties = [], 0
    while len(out) < maxn and p + 4 <= len(body):
        n = struct.unpack_from("<I", body, p)[0]
        if n == 0:
            empties += 1
            if empties >= 5:
                break
            p += 4
            continue
        s = body[p + 4:p + 4 + n]
        if n > 80 or len(s) != n or not re.fullmatch(rb"[\x20-\x7e]+", s):
            break
        empties = 0
        out.append((p, s.decode()))
        p += 4 + n
        if s.endswith(b".dxf"):
            break
    return out


def hdr_name_table(body):
    """(offset, name) of every string in the name table span."""
    p, out = NAME_TABLE[0], []
    while p < NAME_TABLE[1]:
        n = struct.unpack_from("<I", body, p)[0]
        s = body[p + 4:p + 4 + n] if 1 <= n <= 60 else b""
        if s and re.fullmatch(rb"[\x20-\x7e]+", s):
            out.append((p, s.decode()))
            p += 4 + n
        else:
            p += 4
    return out


def records(body, dbg2enum):
    """enum -> (offset, [(offset, token)]) for the first record of each element.  Record start = debug-name string
    with 4 zero bytes before its length."""
    rec = {}
    for m in re.finditer(rb"([\x01-\x50])\x00\x00\x00([A-Z][A-Z0-9_]*)", body):
        if m.start() < TAIL or body[m.start() - 4:m.start()] != b"\0\0\0\0":
            continue
        s = m.group(2)
        if len(s) != m.group(1)[0]:
            continue
        s = s.decode()
        e = dbg2enum.get(s)
        if e is None or e in rec:
            continue
        rec[e] = (m.start(), tokens(body, m.start()))
    return rec


def main():
    body = b"".join(dd.iter_body(HDR))
    dbg = enum_debug_names()
    dbg2enum = {}
    for e, s in sorted(dbg.items()):
        dbg2enum.setdefault(s, e)        # duplicates: lowest enum (reported below)
    ndup = len(dbg) - len(set(dbg.values()))
    tail = struct.unpack_from("<i", body, TAIL)[0]
    n6, = struct.unpack_from("<i", body, TAIL + 4)
    n148, = struct.unpack_from("<i", body, TAIL + 8 + 4 * n6)
    el = list(struct.unpack_from(f"<{n6}i", body, TAIL + 8)) + list(struct.unpack_from(f"<{n148}i", body, TAIL + 12 + 4 * n6))
    say(f"enum table: {len(dbg)} entries ({ndup} duplicate strings); element enum lists in hdr tail: {n6} + {n148} = {len(el)} (lead {tail})")
    rec = records(body, dbg2enum)
    say(f"element records found: {len(rec)}; in the tail enum lists: {sum(1 for e in rec if e in el)}")
    names = hdr_name_table(body)
    say(f"hdr name table strings: {len(names)} ({len(set(n for _, n in names))} distinct)")

    # token -> enum candidates
    cand = {}
    for e, (o, toks) in rec.items():
        rcf = [t for _, t in toks if not t.endswith(".dxf")][-1:]
        for k, (to, t) in enumerate(toks):
            if t.endswith(".dxf"):
                continue
            cand.setdefault(t, {}).setdefault(e, []).append((to, "rcf_name" if [t] == rcf and k == len(toks) - 1 - (toks[-1][1].endswith(".dxf")) else f"field{k}"))
    for e, s in dbg.items():
        if s in dbg2enum and dbg2enum[s] == e:
            cand.setdefault(s, {}).setdefault(e, []).append((None, "debug"))

    hdr_names, seen = [], set()
    for o, n in names:
        c = cand.get(n, {})
        # rcf_name/debug hits outrank description fields
        strong = {e: v for e, v in c.items() if any(f in ("rcf_name", "debug", "field0") for _, f in v)}
        use = strong or c
        enum = next(iter(use)) if len(use) == 1 else None
        hdr_names.append(dict(name=n, offset=o, enum=enum, candidates=sorted(use), via=(use[enum][0][1] if enum is not None else None),
                              source=f"{os.path.basename(HDR)} body offset {o}" + (f"; enum {enum} = {os.path.basename(DSTR)} debug table index {enum} ({dbg[enum]}), record at body offset {rec[enum][0]}" if enum is not None and enum in rec else "")))
        seen.add(n)
    mapped = sum(1 for h in hdr_names if h["enum"] is not None)
    amb = [h["name"] for h in hdr_names if len(h["candidates"]) > 1]
    none = [h["name"] for h in hdr_names if not h["candidates"]]
    say(f"name table entries mapped to one enum: {mapped} / {len(hdr_names)}; ambiguous {len(amb)}; no record {len(none)}")
    say(f"ambiguous: {sorted(set(amb))}")
    say(f"no record: {sorted(set(none))}")

    oracle = json.load(open(SEARCH))
    types = []
    for t in sorted(oracle):
        c = cand.get(t, {})
        rn = {e: v for e, v in c.items() if any(f == "rcf_name" for _, f in v)}
        use = rn or c
        e = next(iter(use)) if len(use) == 1 else None
        tok_off = use[e][0][0] if e is not None else None
        types.append(dict(type=t, enum=e, status="vendor" if e is not None else "unmapped", candidates=sorted(use),
                          debug_name=dbg.get(e), hdr_offset=tok_off,
                          source=(f"{os.path.basename(HDR)} body offset {tok_off} (record of element {dbg.get(e)}); "
                                  f"enum = index in {os.path.basename(DSTR)} DSTR_TRANSLATOR::m_dev_element_enum_debug_string_table") if e is not None else "no hdr record carries this string"))
    # oracle comparison (not a table input)
    agree = diff = 0
    for t in types:
        a = oracle[t["type"]]["phaseB"][0]
        strong = a[1] >= 1 and a[2] and a[1] / a[2] >= 0.99
        if not strong:
            continue
        if t["enum"] == a[0]:
            agree += 1
        else:
            diff += 1
            say(f"ORACLE DIFF {t['type']}: vendor {t['enum']} oracle {a[0]}")
    ten = {"R4": 268, "C4": 275, "LOCAL_INTERCONNECT": 282, "LE_BUFFER": 45, "C16": 281, "R24": 273, "LAB_CLK": 300,
           "BLK_CLK_BUF": 568, "SCLK_TO_ROWCLK_BUF": 667, "GLOBAL_CLK_V": 299}
    ok10 = sum(1 for t in types if t["type"] in ten and t["enum"] == ten[t["type"]])
    say(f"oracle: 10 derived enums matched {ok10} / 10; all oracle-consistent types (>=99% edges): agree {agree}, differ {diff}")
    say(f"RCF types: {len(types)}; vendor-decoded {sum(1 for t in types if t['enum'] is not None)}; unmapped {[t['type'] for t in types if t['enum'] is None]}")
    for t in types:
        say(f"  {t['type']:26s} {t['enum']} {t['debug_name']} cand={t['candidates']}")
    json.dump(dict(types=types, hdr_names=hdr_names), open(OUT, "w"), indent=1)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, "w").write("\n".join(_log) + "\n")


main()
