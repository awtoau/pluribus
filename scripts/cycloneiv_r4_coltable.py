#!/usr/bin/env python3.15t
"""Measured LB -> R4 per-column table (dx, df) as a lookup (#162, flag PLURIBUS_R4_COLTABLE, default off).

Source: the newest derived-table evidence row 'R4 per-column (dx, df) table by source rel (N arcs)'
(written by scripts/cycloneiv_r4_relcol.py coltable --nulls).  Key (destination column X, rel = source LAB X - X).
Only cells with ONE distinct (dx, df) are used; mixed / data-only cells are absent => unresolved => counted missing.
dx = destination record vx - vx of column X; df = plane-frame shift of the group cells (rigid, same v).
"""
import ast
import hashlib
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_T = None
import collections
NOCELL = collections.Counter()      # (dest X, rel) -> LB -> R4 hops without a table cell (diagnostic)


def enabled():
    return os.environ.get("PLURIBUS_R4_COLTABLE", "0") != "0"


def table():
    """{(X, rel): (dx, df)} from the DB row; cached."""
    global _T
    if _T is not None:
        return _T
    os.environ.setdefault("PLURIBUS_SQLITE_PATH", os.path.join(REPO, "databases", "cycloneiv", "gx150.db"))
    sys.path.insert(0, REPO)
    import db
    import schema as S
    from sqlalchemy import select
    with db.engine().connect() as c:
        r = c.execute(select(S.evidence.c.result).where((S.evidence.c.family == "cycloneiv") & (S.evidence.c.kind == "derived-table") &
                                                        S.evidence.c.name.like("R4 per-column (dx, df) table%"))
                      .order_by(S.evidence.c.id.desc())).first()
    if r is None:
        raise SystemExit("PLURIBUS_R4_COLTABLE=1 but no 'R4 per-column (dx, df) table' derived-table row in the DB")
    t = {}
    for key, v in r[0]["file"].items():
        vals = [k for k in v["values"] if not k.startswith("data:")]
        if len(vals) == 1:
            x, rel = (int(a) for a in key.split(","))
            t[(x, rel)] = ast.literal_eval(vals[0])
    _T = t
    return t


def tag():
    """Cache-key suffix for caches that depend on the table."""
    if not enabled():
        return ""
    return "_col" + hashlib.sha1(repr(sorted(table().items())).encode()).hexdigest()[:8]


def apply(D):
    """Shift the group cells of every LB -> R4 edge matched by a table cell (dest column X, rel) by +df frames, in D.P.dec.pf.
    Edge (s, d): X = column with table[(X, col(s) - X)] = (dx, df) and vx(d) = vx(X) + dx; ambiguous df or no cell => unchanged.
    The table supersedes the PLURIBUS_HOP_OVERRIDE shift for the edges it covers."""
    import numpy as np
    dec = D.P.dec
    ge, Q, P = D.Q.ge, D.Q, D.P
    gdest, grec = D.gdest, D.grec
    t = table()
    cols = sorted(D.cm)
    xs_of_vx = D.x_of_vx
    g_ok = (gdest >= 0) & (Q.enum[np.maximum(gdest, 0)] == 268) & (Q.enum[grec] == 45)
    gi = np.flatnonzero(g_ok)
    vs, vd = P.vx[grec[gi]].astype(np.int64), P.vx[gdest[gi]].astype(np.int64)
    xs = np.array([xs_of_vx.get(int(v), -1) for v in vs.tolist()])
    dfs = np.full(len(gi), 10 ** 6, np.int64)
    amb = np.zeros(len(gi), bool)
    for rel in (-1, 0, 3, 4):
        X = xs - rel
        for i in np.flatnonzero((xs >= 0) & np.isin(X, cols)).tolist():
            cell = t.get((int(X[i]), rel))
            if cell and vd[i] - D.cm[int(X[i])] == cell[0]:
                if dfs[i] not in (10 ** 6, cell[1]):
                    amb[i] = True
                dfs[i] = cell[1]
    hit = (dfs != 10 ** 6) & ~amb
    shift = np.zeros(len(dec.gsize), np.int64)
    shift[gi[hit]] = dfs[hit]
    raw = np.asarray(dec.pf)
    gid = np.asarray(dec.gid)
    out = raw.astype(np.int64)
    e = np.flatnonzero((shift[gid] != 0) & (raw != 30000))
    out[e] = np.asarray(dec.pf_raw).astype(np.int64)[e] + shift[gid[e]]      # supersedes the hop-override shift on these edges
    dec.pf_tag = dec.pf_tag + tag()
    import cycloneiv_asm_decode as AD
    path = f"{AD.DEC}_pf{dec.pf_tag}.npy"
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as fh:
        np.save(fh, out.astype(np.int32))
    os.replace(tmp, path)
    dec.pf = np.load(path, mmap_mode="r")
    return {"edges": int(g_ok.sum()), "shifted": int(hit.sum()), "ambiguous": int(amb.sum()), "entries": int(len(e))}
