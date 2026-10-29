"""O2: forced LB -> R4 arcs (specimen base/spec raw diffs from tmp/hop_specimens/results_r4*.json).

Per candidate of the open address -> plane interface, no shift of any kind:
- STRICT: every cell of the destination's group in the source's fan-out lies in the raw diff (on + off) of the pair.
  Reported for all group entries and for the entries programmed by the asm.ddb flag rule (select b0 == +1, or b1 == -1).
- TILE: some record owning >= 2 flipped (on) cells sits at the source tile, and one at the destination tile (record x/y raw = fitter X/Y, A8).
Two ways to pick the records: CLEAN = A7 exact names (source LE_BUFFER:X,Y,I and destination R4:X,Y,I from the row's names);
ROWS = the record ids stored in the rows (taken from the retired stack; reported for comparison only).
The diff keys use the plane key (file frame * 6368 + lane-7-first v) the rows were written in; a cell at byte 793 has no key there and counts as unverifiable.
"""
import collections
import glob
import json
import os

import numpy as np
import pytest

from conftest import REPO, report
from lifters.cycloneiv_clean import ddb, names
from lifters.cycloneiv_clean import plane as P

NV = 6368
LB, R4 = names.enum_of("LE_BUFFER"), names.enum_of("R4")   # names_table.json
CHUNK = 4_000_000


def arcs():
    rows = {}
    for f in sorted(glob.glob(os.path.join(REPO, "tmp", "hop_specimens", "results_r4*.json"))):
        for r in json.load(open(f))["rows"]:
            if r.get("wire") == "R4" and r.get("honoured") and r.get("cands"):
                rows.setdefault((r["src"], tuple(r["tile"]), r["I"]), r)
    return list(rows.values())


def keys_of(cand, addr, tables):
    """Old-style plane keys of raw addresses; -1 where the cell has no key (invalid frame or byte 793)."""
    r, j, k = P.CANDIDATES[cand](addr, tables)
    ok = (r >= 0) & (j <= P.ROWS - 1)
    return np.where(ok, P.plane_frame(np.maximum(r, 0)) * NV + P.plane_v(j, k), -1)


@pytest.fixture(scope="module")
def rows():
    a = arcs()
    if not a:
        pytest.skip("local data missing: tmp/hop_specimens/results_r4*.json")
    return a


@pytest.fixture(scope="module")
def clean_ids(rows, routing):
    """A7: (src record, dest record) by exact element key; None when the name is not exactly one record."""
    k = routing.element_keys()
    order = np.argsort(k, kind="stable")
    sk = k[order]

    def one(key):
        a, b = np.searchsorted(sk, key, "left"), np.searchsorted(sk, key, "right")
        return int(order[a]) if b - a == 1 else None

    out = []
    for r in rows:
        s = one(ddb.element_key(LB, r["lb"][1], r["lb"][2], 0, r["lb"][3]))
        d = one(ddb.element_key(R4, r["wire_name"][1], r["wire_name"][2], 0, r["wire_name"][3]))
        out.append((s, d))
    return out


def group_of(routing, asm, s, d):
    f = routing.fanout(s)
    hit = np.flatnonzero(f == d)
    if len(hit) != 1 or hit[0] >= len(asm.group_sizes(s)):
        return None
    return asm.group_slice(s, int(hit[0]))


def test_o2_strict(rows, clean_ids, routing, asm, tables):
    report("O2-arcs", arcs=len(rows), clean_src=sum(s is not None for s, _ in clean_ids),
           clean_dst=sum(d is not None for _, d in clean_ids),
           clean_dst_in_src_fanout=sum(1 for s, d in clean_ids if s is not None and d is not None and d in set(routing.fanout(s).tolist())))
    for how in ("clean", "rows"):
        groups = []
        for r, (cs, cd) in zip(rows, clean_ids):
            s, d = (cs, cd) if how == "clean" else (r["src"], r["resolved"]["rec"] if r.get("resolved") else None)
            groups.append(None if s is None or d is None else group_of(routing, asm, s, d))
        for cand in sorted(P.CANDIDATES):
            res = collections.Counter()
            for r, g in zip(rows, groups):
                if g is None:
                    res["no_group"] += 1
                    continue
                diff = set(r["on"]) | set(r["off"])
                addr = asm.addr(g)
                key = keys_of(cand, addr, tables)
                b0, b1 = asm.flags(g)
                prog = (b0 == 1) | (b1 == -1)
                if (key < 0).any():
                    res["unverifiable"] += 1
                    continue
                res["all_entries"] += all(int(x) in diff for x in key)
                res["programmed_entries"] += all(int(x) in diff for x in key[prog])
            report("O2-strict", how=how, candidate=cand, arcs=len(rows), **dict(res))
    assert len(rows) > 0


def test_o2_tile(rows, clean_ids, routing, asm, tables):
    on_all = sorted({int(c) for r in rows for c in r["on"]})
    qa = np.array(on_all, np.int64)
    for cand in sorted(P.CANDIDATES):
        hit_key, hit_rec = [], []
        n = len(asm.pos)
        for a in range(0, n, CHUNK):
            sl = slice(a, min(a + CHUNK, n))
            key = keys_of(cand, asm.addr(sl), tables)
            pos = np.searchsorted(qa, key)
            m = (key >= 0) & (qa[np.minimum(pos, len(qa) - 1)] == key)
            hit_key.append(key[m])
            hit_rec.append(np.asarray(asm.rec[sl])[m])
        hk, hr = np.concatenate(hit_key), np.concatenate(hit_rec)
        by_cell = collections.defaultdict(set)
        for c, rc in zip(hk.tolist(), hr.tolist()):
            by_cell[c].add(rc)
        res = collections.Counter()
        for r in rows:
            owners = collections.Counter(rc for c in r["on"] for rc in by_cell.get(int(c), ()))
            sx, sy = r["lb"][1], r["lb"][2]
            dx, dy = r["tile"]
            s_ok = any(n_ >= 2 and routing.x[rc] == sx and routing.y[rc] == sy for rc, n_ in owners.items())
            d_ok = any(n_ >= 2 and routing.x[rc] == dx and routing.y[rc] == dy for rc, n_ in owners.items())
            res[(s_ok, d_ok)] += 1
        report("O2-tile", candidate=cand, arcs=len(rows), both=res[(True, True)], source_only=res[(True, False)],
               dest_only=res[(False, True)], neither=res[(False, False)])
