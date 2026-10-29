#!/usr/bin/env python3.15t
"""Generate lifters/cycloneiv_clean/names_table.json from the vendor hdr.ddb and the edge-consistency search (#165).

  python3.15t scripts/cycloneiv_clean_names_search.py   # -> tmp/logs/cycloneiv_clean_names_search.json
  python3.15t scripts/cycloneiv_clean_names_table.py

types[]: RCF type string, enum (routing.ddb element enum, null = not derived), status, edge/unique evidence, source.
hdr_names[]: every name:int32 pair of the stingray4 hdr.ddb name table (offset in the inflated body); the int is a
hash-table field, not decoded to an enum.  Rule: derived = >= 99 % of >= 1,000 edges consistent (phase B).
"""
import json
import os
import re
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_ddb_decode as dd  # noqa: E402

HDR = "/mnt/2tb/opt/altera/quartus-25.1/quartus/common/devinfo/cycloneivgx/ddb_stingray4_hdr.ddb"
SEARCH = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_names_search.json")
OUT = os.path.join(REPO, "lifters", "cycloneiv_clean", "names_table.json")
MIN_EDGES, MIN_FRAC = 1000, 0.99


def hdr_pairs(body):
    p, toks = 23440, []        # name table start: first aligned token run, see docs
    while p < 30000:
        n, = struct.unpack_from("<I", body, p)
        s = body[p + 4:p + 4 + n] if 1 <= n <= 60 else b""
        if s and re.fullmatch(rb"[\x20-\x7e]+", s):
            toks.append((p, "S", s.decode())); p += 4 + n
        else:
            toks.append((p, "i", struct.unpack_from("<i", body, p)[0])); p += 4
    return [(t[0], t[2], toks[k + 1][2]) for k, t in enumerate(toks[:-1]) if t[1] == "S" and toks[k + 1][1] == "i"]


def hdr_offset(body, name):
    m = re.search(struct.pack("<I", len(name)) + re.escape(name.encode()), body)
    return m.start() if m else None


def main():
    body = b"".join(dd.iter_body(HDR))
    res = json.load(open(SEARCH))
    types = []
    for t, v in sorted(res.items()):
        a, b = v["phaseB"][0], (v["phaseB"][1] if len(v["phaseB"]) > 1 else None)
        e, ok, tot, uq = a
        frac = ok / tot if tot else 0.0
        if tot >= MIN_EDGES and frac >= MIN_FRAC:
            status = "derived"
        elif tot >= 1 and frac >= MIN_FRAC:
            status = "consistent-few-edges"
        else:
            status = "unmapped"
        types.append(dict(
            type=t, enum=e if status != "unmapped" else None, status=status, edges=tot, edges_ok=ok,
            unique_pct=round(100 * uq, 2) if status != "unmapped" else None,
            runner_up=dict(enum=b[0], edges_ok=b[1]) if b and status != "unmapped" else None,
            names=v["names"], unique_cands=v["unique_cands"], hdr_offset=hdr_offset(body, t),
            source=f"enum: routing.ddb element enum, edge consistency over corpus RCF trees (cycloneiv_clean_names_search.py); name: {os.path.basename(HDR)} body offset"))
    names = [dict(name=n, offset=p, hdr_int=v, source=f"{os.path.basename(HDR)} body offset {p}") for p, n, v in hdr_pairs(body)]
    json.dump(dict(types=types, hdr_names=names), open(OUT, "w"), indent=1)
    c = {s: sum(1 for t in types if t["status"] == s) for s in ("derived", "consistent-few-edges", "unmapped")}
    print(len(types), c, len(names))


main()
