#!/usr/bin/env python3
"""Parse a Quartus .rcf (quartus_cdb --back_annotate=routing) into rcf_routes.

Grammar (docs/altera/cycloneV/cyclonev-rcf-oracle.md):
  signal_name = <net> { <stmt>* }
  stmt: TYPE:X<x>Y<y>S<n>I<idx>;            routing element
        TYPE:X<x>Y<y>S<n>B:<port path>;     block-port element (IO/HMC/clock buffers)
        label = <name>, <elem>;             fan-out point, <elem> = implicit element
        branch_point = <name>;              next branch leaves from that label
        dest = ( <atom>, <port> )[, route_port = <port>];   ends a branch
- Unrecognised lines are a hard error (db.die).

Usage: python3.15t scripts/cyclonev_rcf_parse.py <file.rcf> [...]   # counts only
Called by scripts/cyclonev_corpus_build.py as load_rcf(build_id, path).
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import db  # noqa: E402

_NET = re.compile(r"^signal_name = (.*) \{$")
_IDX = re.compile(r"^(\w+):X(\d+)Y(\d+)S(\d+)I(\d+)$")
_BLK = re.compile(r"^(\w+):X(\d+)Y(\d+)S(\d+)B:(.+)$")
_LABEL = re.compile(r"^label = (\S+), (\S+);$")
_BRANCH = re.compile(r"^branch_point = (\S+);$")
_DEST = re.compile(r"^dest = \( (.*), ([^,()]+) \)(?:, route_port = ([^;]+))?;$")


def parse_elem(text):
    """-> dict(element, x, y, n, idx, port_path) or None."""
    m = _IDX.match(text)
    if m:
        return dict(element=m.group(1), x=int(m.group(2)), y=int(m.group(3)),
                    n=int(m.group(4)), idx=int(m.group(5)), port_path=None)
    m = _BLK.match(text)
    if m:
        return dict(element=m.group(1), x=int(m.group(2)), y=int(m.group(3)),
                    n=int(m.group(4)), idx=None, port_path=m.group(5))
    return None


def parse(path):
    rows = []
    net = None
    branch = -1
    cur = []          # rows of the open branch
    parent = (None, None)
    skip = False      # inside a non-route `section <name> { ... }` (e.g. ram_sublocations)
    for i, ln in enumerate(Path(path).read_text().split("\n"), 1):
        s = ln.strip()
        if skip:
            skip = s != "}"
            continue
        if s.startswith("section "):
            skip = True
            continue
        if not s or s.startswith("###") or s.startswith("device ") \
                or s.startswith("rcf_written_by"):
            continue
        if s == "}":
            if net is not None and cur:
                db.die(f"{path}:{i}: net {net!r} ends with elements and no dest")
            net = None
            continue
        m = _NET.match(s)
        if m:
            net, branch, cur, parent = m.group(1), -1, [], (None, None)
            continue
        if net is None:
            db.die(f"{path}:{i}: statement outside a signal_name block: {s!r}")
        m = _BRANCH.match(s)
        if m:
            parent = (None, m.group(1))     # parent branch resolved below via label table
            continue
        m = _LABEL.match(s)
        if m:
            e = parse_elem(m.group(2))
            if e is None:
                db.die(f"{path}:{i}: bad label element {s!r}")
            cur.append(dict(e, kind="label", raw=s, label=m.group(1)))
            continue
        m = _DEST.match(s)
        if m:
            branch += 1
            # no branch_point = branch leaves from the net's driver (root)
            for h, r in enumerate(cur):
                rows.append(dict(r, net=net, branch=branch, hop=h,
                                 parent_branch=None, parent_label=parent[1],
                                 dest_atom=m.group(1), dest_port=m.group(2),
                                 route_port=m.group(3)))
            if not cur:     # branch with no own elements: keep a marker row so the dest is recorded
                rows.append(dict(kind="dest", element="", x=None, y=None, n=None, idx=None,
                                 port_path=None, raw=s, label=None, net=net, branch=branch,
                                 hop=0, parent_branch=None, parent_label=parent[1],
                                 dest_atom=m.group(1), dest_port=m.group(2),
                                 route_port=m.group(3)))
            cur, parent = [], (None, None)
            continue
        if s.endswith(";"):
            e = parse_elem(s[:-1])
            if e is not None:
                cur.append(dict(e, kind="elem", raw=s, label=None))
                continue
        db.die(f"{path}:{i}: unrecognised RCF line {s!r}")
    # resolve parent_branch: the branch (same net) whose label row carries parent_label
    owner = {}
    for r in rows:
        if r["label"]:
            owner.setdefault((r["net"], r["label"]), r["branch"])
    for r in rows:
        if r["parent_label"]:
            pb = owner.get((r["net"], r["parent_label"]))
            if pb is None:
                db.die(f"net {r['net']!r}: branch_point {r['parent_label']!r} has no label")
            r["parent_branch"] = pb
    return rows


def load_rcf(build_id, path):
    import schema
    from sqlalchemy import delete, insert
    rows = parse(path)
    t = schema.rcf_routes
    cols = {c.name for c in t.c}
    with db.engine().begin() as conn:
        conn.execute(delete(t).where(t.c.build == build_id))
        if rows:
            conn.execute(insert(t), [dict({k: v for k, v in r.items() if k in cols},
                                          build=build_id) for r in rows])
    return len(rows)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        r = parse(p)
        print(f"{p}: {len({x['net'] for x in r})} nets, "
              f"{len({(x['net'], x['branch']) for x in r})} branches, {len(r)} rows")
