#!/usr/bin/env python3
"""Parse a quartus_sta `report_timing -detail full_path -show_routing` file into route_hops.

- Keeps every hop of every reported path (no dedupe); path ids restart per analysis.
- Unrecognised rows inside a Data Arrival/Required table are a hard error (db.die).

Usage: python3.15t scripts/cyclonev_route_parse.py <route_report.txt> [...]   # counts only
Called by scripts/cyclonev_corpus_build.py as load_routes(build_id, path).
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import db  # noqa: E402

_PATH = re.compile(r"^Path #(\d+): (\w+) slack is ")
_PROP = re.compile(r"^; (From Node|To Node)\s+; (.*?)\s*;$")
_ROW = re.compile(r"^;( *)(-?[\d.]+) +; +(-?[\d.]+) +; *(\w*) *; *(\w*) *; *(\d*) *; *(\S*) *; (.*?) *;$")
_LOC = re.compile(r"^([A-Z0-9_]+?)_X(\d+)_Y(\d+)_N(\d+)(?:_I(\d+))?$")
_LOC_OTHER = re.compile(r"^([A-Z0-9]+)_\w+$")


def parse_loc(loc):
    if not loc:
        return None, None, None, None, None
    m = _LOC.match(loc)
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), \
            int(m.group(5)) if m.group(5) else None
    m = _LOC_OTHER.match(loc)
    if m:
        return m.group(1), None, None, None, None
    db.die(f"unrecognised route location {loc!r}")


def parse(path):
    hops = []
    analysis = pnum = part = None
    props = {}
    hop = 0
    for i, ln in enumerate(Path(path).read_text().split("\n"), 1):
        m = _PATH.match(ln)
        if m:
            pnum, analysis, part, props = int(m.group(1)), m.group(2).lower(), None, {}
            continue
        m = _PROP.match(ln)
        if m and pnum is not None and part is None:
            props[m.group(1)] = m.group(2)
            continue
        if ln.startswith("; Data Arrival Path"):
            part, hop, section, driver = "arrival", 0, None, None
            continue
        if ln.startswith("; Data Required Path"):
            part, hop, section, driver = "required", 0, None, None
            continue
        if part is None:
            continue
        if ln.startswith("+") or ln.startswith("; Total") or not ln.strip():
            if not ln.strip():
                part = None
            continue
        m = _ROW.match(ln)
        if not m:
            db.die(f"{path}:{i}: unrecognised route row {ln!r}")
        indent, total, incr, rf, typ, fanout, loc, elem = m.groups()
        kind, x, y, n, idx = parse_loc(loc)
        if not indent:
            section, driver = elem, None
        hops.append(dict(section=section, driver=driver,analysis=analysis, path=pnum, from_node=props.get("From Node"),
                         to_node=props.get("To Node"), part=part, hop=hop,
                         depth=len(indent) // 2, total=float(total), incr=float(incr),
                         rf=rf or None, type=typ or None, fanout=int(fanout) if fanout else None,
                         location=loc or None, loc_kind=kind, x=x, y=y, n=n, idx=idx,
                         element=elem))
        if typ == "CELL" and "|" in elem:
            driver = elem
        hop += 1
    return hops


def load_routes(build_id, path):
    import schema
    from sqlalchemy import delete, insert
    hops = parse(path)
    t = schema.route_hops
    with db.engine().begin() as conn:
        conn.execute(delete(t).where(t.c.build == build_id))
        if hops:
            conn.execute(insert(t), [dict(h, build=build_id) for h in hops])
    return len(hops)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        h = parse(p)
        paths = {(x["analysis"], x["path"]) for x in h}
        print(f"{p}: {len(paths)} paths, {len(h)} hops, "
              f"{sum(1 for x in h if x['type'] == 'RE')} RE hops")
