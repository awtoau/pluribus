"""Cyclone IV GX IO setting tables from the asmdb dirt ddb (vendor data, no pair builds) (#168).

Source: ddb_stingray4_asmdb_dirt.ddb, root child ARCH_GROUPS (17 groups); each group = ARCH_GROUP_TYPE, ARCH_GROUP_BLOCK_TYPE and ARCH_GROUP_DATA rows of
(IO_STANDARD | VOLTAGE_LEVEL string, SETTINGS integer).  The IO groups present: MIO_SELECT_IOST_DIRT (IO standard -> IOST value, per block type) and
MIO_SET_PULLDOWN_STRENGTH / MIO_SET_PULLUP_STRENGTH (VCCIO level -> strength value, HIO and VIO).
Integer decode: an INTEGER node's first element is a delta against the previous INTEGER node of the file (pool order = node order), so the absolute
SETTINGS value is the running sum over all integer nodes (docs/altera/cycloneIV/cycloneiv-clean-io.md, dirt pool format; scripts/cycloneiv_clean_dirt.py).
The value -> bit pattern law is io_encode.py (element k = value bit k).
"""
import os
import sys

from . import plane as P

IO_GROUPS = ("MIO_SELECT_IOST_DIRT", "MIO_SET_PULLDOWN_STRENGTH", "MIO_SET_PULLUP_STRENGTH")      # source: dirt ARCH_GROUP_TYPE names carrying IO tables
_cache = {}


def _dirt():
    sys.path.insert(0, os.path.join(P.REPO, "scripts"))
    import cycloneiv_clean_dirt as D
    p = os.path.join(D.QROOT, "common", "devinfo", "cycloneivgx", "ddb_stingray4_asmdb_dirt.ddb")
    nodes, ok = D.decode_dirt(p)
    if not ok:
        raise ValueError("dirt ddb not fully consumed")
    return D, nodes


def tables():
    """{(ARCH_GROUP_TYPE, block type): [(key string, absolute SETTINGS)]} for the IO groups."""
    if _cache:
        return _cache
    D, nodes = _dirt()
    names = D.enum_tables()["dirt_type"]
    acc = 0
    for n in nodes:
        if n["cls"] == 3 and n["val"]:
            acc += n["val"][0]
            n["abs"] = acc
    nm = lambda n: names.get(n["idx"], n["idx"]) if n["flag"] == 1 else n["idx"]
    ag = nodes[nodes[0]["ch"][[nm(nodes[c]) for c in nodes[0]["ch"]].index("ARCH_GROUPS")]]
    for c in ag["ch"]:
        kids = {nm(nodes[k]): k for k in nodes[c]["ch"]}
        typ, blk = nodes[kids["ARCH_GROUP_TYPE"]]["val"][0], nodes[kids["ARCH_GROUP_BLOCK_TYPE"]]["val"][0]
        if typ not in IO_GROUPS:
            continue
        rows = []
        for k in nodes[kids["ARCH_GROUP_DATA"]]["ch"]:
            kk = {nm(nodes[x]): nodes[x] for x in nodes[k]["ch"]}
            rows.append(((kk.get("IO_STANDARD") or kk["VOLTAGE_LEVEL"])["val"][0], kk["SETTINGS"]["abs"]))
        _cache[(typ, blk)] = rows
    return _cache
