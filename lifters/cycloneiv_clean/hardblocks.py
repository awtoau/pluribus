"""Cyclone IV GX (EP4CGX150) non-LAB blocks: class -> arch group binding and absolute-address group bits.  Vendor-derived only (#169).

- class_groups_table.json (scripts/cycloneiv_clean_class_bind.py): rows enum / group / cls / lib / source.  Read from the vendor lib machine
  code: each `ASM_ASMDBIO::search_for_*_arch_groups` (and asmgx_search_for_arch_groups) switches on ASMDB_ARCH_GROUP_TYPE (this+0xc) and
  news the processing class.  13 of 13 option-register groups pair-confirmed in options_table.json reproduce their `group_type`.
- Absolute groups: std / dumb / stlmap groups carry no BLOCK_INFO; their stored mux bits ARE addresses (CRAM tag 0, CFF 0xA, option /
  DPRIO 0x8 (0x88 option, 0x84 DPRIO), 0xC / 0xF markers).  Only calc groups (LAB / MEAB / MAC) are base + offset
  (ASMDB_BLOCK_INFO::calculate_bits_traditional @0x8e8a4: abs = (off / ram_cols + hi) * ram_cols + off % ram_cols + lo = off + hi * ram_cols + lo;
  CFF = off + list[3][i]).
"""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE_PATH = os.path.join(HERE, "class_groups_table.json")
# source: libdb_asmdb ASMDB_BLOCK_INFO::calculate_bits_traditional @0x8e8a4 (tag tests), docs/cycloneiv-address-spaces.md 2.1
SPACE_OF_TAG = {0x0: "cram", 0xA: "cff", 0x8: "option_dprio", 0xC: "marker", 0xF: "marker"}
_rows = []


def rows():
    if not _rows:
        _rows.extend(json.load(open(TABLE_PATH)))
    return _rows


def groups_of(cls):
    """{group type name: enum} the class ASM_X is bound to by a factory switch."""
    return {r["group"]: r["enum"] for r in rows() if r["cls"] == cls}


def classes_of(group):
    return sorted({r["cls"] for r in rows() if r["group"] == group})


def group_bits(w, g):
    """raw stored mux bits of one walk group (std / stlmap: path muxes, dumb: bit list)."""
    if g["cls"] == 7:
        return list(g["bits"])
    return [b for p in g["paths"] for r in p if r for b in w.mux(r)["bits"]]


def absolute_bits(w, names):
    """{(block, group name): {space: sorted distinct addresses}} over the non-calc groups of a walk (names = dirt.enum_tables())."""
    out = collections.defaultdict(lambda: collections.defaultdict(set))
    for g in w.groups():
        if g["cls"] == 5:
            continue
        key = (names["block_type"].get(g["btype"], str(g["btype"])), names["arch_group_type"].get(g["type"], str(g["type"])))
        for b in group_bits(w, g):
            sp = SPACE_OF_TAG.get(b >> 28, "other")
            if sp != "marker":
                out[key][sp].add(b & (0x7FFFFFFF if sp == "cram" else 0x0FFFFFFF if sp == "cff" else 0xFFFFFFFF))
    return {k: {s: sorted(v) for s, v in d.items()} for k, d in out.items()}
