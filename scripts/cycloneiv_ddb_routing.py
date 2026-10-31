#!/usr/bin/env python3.15t
"""Cyclone IV GX `routing.ddb` readers.  Format: docs/altera/cycloneIV/cycloneiv-ddb-format.md "routing.ddb".

  python3.15t scripts/cycloneiv_ddb_routing.py fanout [--die stingray4]  # EXACT decode -> <die>_rt_fanout.npz

`fanout` is the exact, self-validating decode (element table + template pool + fan-in inversion
proof; schemas recovered from libddb_dygr.so by scripts/cycloneiv_ddb_symdump.py):
dests(elem) = V(elem) + template offsets.  Gate: scripts/cycloneiv_ddb_fanout.py check.

`nodes` / `twin` / `templates` are the older partial readers (tile table, first-fan-in map read as
a twin map, resync template parse); superseded by `fanout`, kept while cycloneiv_ddb_fanout.py
gt/solve still load their caches.  Log tmp/logs/cycloneiv_ddb_routing.log.
"""
import argparse
import collections
import logging
import os
import re
import struct
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_ddb_decode as dd  # noqa: E402
import cycloneiv_ddb_asm as A  # noqa: E402

log = logging.getLogger("cycloneiv_ddb_routing")
NODE = np.dtype([("dx", "<i2"), ("dy", "<i2"), ("c", "<i4"), ("dn", "<i4")])
TWIN_OFF = {"stingray4": 22469517}       # after the u32 N landmark at 22,469,513
TPL_START = {"stingray4": 63120855}      # first template of the solid chain (earlier area differs)


def nodes(die):
    path = f"{A.DEVINFO}/ddb_{die}_routing.ddb"
    blocks = dd.iter_body(path)
    buf = bytearray()
    need = 16
    while len(buf) < need:
        buf.extend(next(blocks))
    ver, cols, rows, n = struct.unpack_from("<IIII", buf, 0)
    if ver != 4:
        raise dd.DdbError(f"routing body version {ver}")
    need = 16 + 12 * n
    for blk in blocks:
        buf.extend(blk)
        if len(buf) >= need:
            break
    rec = np.frombuffer(bytes(buf[16:need]), NODE)
    x, y = np.cumsum(rec["dx"]), np.cumsum(rec["dy"])
    if x.min() < 0 or x.max() >= cols or y.min() < 0 or y.max() >= rows:
        raise dd.DdbError(f"node tiles outside {cols} x {rows}: x {x.min()}..{x.max()} y {y.min()}..{y.max()}")
    os.makedirs(A.TMP, exist_ok=True)
    out = os.path.join(A.TMP, f"{die}_rt_nodes.npy")
    np.save(out, rec)
    off = np.cumsum(rec["dn"].astype(np.int64))
    log.info("%s: %d nodes in a %d x %d grid; tiles x %d..%d y %d..%d; fan-out list offsets %d..%d; dn hist %s; wrote %s",
             die, n, cols, rows, x.min(), x.max(), y.min(), y.max(), off.min(), off.max(),
             collections.Counter(rec["dn"].tolist()).most_common(6), out)
    return rec


def body(die):
    """Whole inflated body as bytes (88 MB; cached in tmp/ddb)."""
    os.makedirs(A.TMP, exist_ok=True)
    cache = os.path.join(A.TMP, f"{die}_routing.bin")
    if not os.path.exists(cache):
        with open(cache, "wb") as f:
            for blk in dd.iter_body(f"{A.DEVINFO}/ddb_{die}_routing.ddb"):
                f.write(blk)
    return open(cache, "rb").read()


def cum_ids(f0):
    """Delta stream -> absolute ids: restart where value < -2^30 (restart value = v + 2^31);
    stored id + 1, so subtract 1 (-1 = NULL)."""
    f0 = np.asarray(f0, np.int64)
    rest = f0 < -(1 << 30)
    d = np.where(rest, f0 + (1 << 31), f0)
    cs = np.cumsum(np.where(rest, 0, d))
    o = d - cs
    idx = np.arange(len(f0))
    last = np.maximum.accumulate(np.where(rest, idx, -1))
    return cs + np.where(last >= 0, o[np.maximum(last, 0)], 0) - 1


def twin(die):
    """Section 2: per-node other-end record id (-1 = none).  Verified: every named H4/V4/H24/V16
    pair maps to the same wire's other-end name (same type, row/col and span 1..30)."""
    raw = body(die)
    n_nodes = {t[5]: t[3] for t in dd.read_types(f"{A.DEVINFO}/ddb_{die}_routing.ddb")}
    n = struct.unpack_from("<I", raw, TWIN_OFF[die] - 4)[0]
    sec = np.frombuffer(raw, "<i4", count=3 * n, offset=TWIN_OFF[die]).reshape(n, 3)
    tw = cum_ids(sec[:, 0])
    out = os.path.join(A.TMP, f"{die}_rt_twin.npy")
    np.save(out, tw)
    # verify against icnames
    import pickle
    names_pkl = os.path.join(A.TMP, f"{die}_dec_names.pkl")
    tot = ok = 0
    if os.path.exists(names_pkl):
        names = pickle.load(open(names_pkl, "rb"))
        pat = re.compile(r"^(H4|V4|H24|V16)R(\d+)C(\d+)(RT|LT|UP|DN)\[(\d+)\]$")
        for r, nm in names.items():
            m = pat.match(nm)
            t = int(tw[r]) if r < n else -1
            if m is None or not 0 <= t < n:
                continue
            m2 = pat.match(names.get(t, ""))
            if m2 is None:
                continue
            tot += 1
            same = 2 if m.group(1) in ("H4", "H24") else 3
            d = int(m2.group(5 - same)) - int(m.group(5 - same))
            ok += m.group(1) == m2.group(1) and m.group(same) == m2.group(same) and 1 <= abs(d) <= 30
    log.info("%s: twin map for %d nodes -> %s; NULL %d; named-pair check %d/%d", die, n, out,
             int((tw < 0).sum()), ok, tot)
    if tot and ok != tot:
        dd.DdbError(f"twin name check failed: {ok}/{tot}")
    return tw


def templates(die):
    """Fan-out template stream: parse from TPL_START, resync over unmodeled stretches.
    Writes <die>_rt_tpl.npz: pos/na/nd/flag per template + concatenated deltas (int32) and
    attrs (uint16) with per-template offsets."""
    raw = body(die)
    L = len(raw)
    u32 = struct.Struct("<I").unpack_from
    i16 = struct.Struct("<h").unpack_from

    def parse_one(p):
        if p + 21 > L:
            return None
        v, = u32(raw, p)
        if v <= 2000:
            q = p + 4 + 2 * v
            if q + 17 <= L and i16(raw, q)[0] == i16(raw, q + 6)[0]:
                nd, = u32(raw, q + 11)
                if nd <= 2000 and i16(raw, q)[0] == nd - v:
                    return (q + 17 + 4 * (nd - 1) if nd else q + 17, v, nd, q)
        if i16(raw, p)[0] == i16(raw, p + 6)[0]:
            nd, = u32(raw, p + 11)
            if nd <= 2000 and i16(raw, p)[0] == nd:
                return (p + 17 + 4 * (nd - 1) if nd else p + 17, 0, nd, p)
        return None

    p = TPL_START[die]
    pos, nas, nds, flags = [], [], [], []
    deltas, attrs = [], []
    gaps = []
    while p < L - 21:
        r = parse_one(p)
        if r is None:
            # resync: scan forward for the next position that chains >= 3 templates
            q = p + 1
            while q < L - 21:
                r2 = parse_one(q)
                if r2 is not None:
                    a, b = r2[0], 1
                    while b < 3 and a is not None:
                        nx = parse_one(a)
                        a, b = (nx[0], b + 1) if nx else (None, b)
                    if b >= 3:
                        break
                q += 1
            if q >= L - 21:
                break
            gaps.append((p, q - p))
            p = q
            continue
        p2, na, nd, qm = r
        pos.append(p)
        nas.append(na)
        nds.append(nd)
        flags.append(struct.unpack_from("<b", raw, qm + 8)[0])
        if na:
            attrs.append(np.frombuffer(raw, "<u2", count=na, offset=p + 4))
        if nd > 1:
            deltas.append(np.frombuffer(raw, "<i4", count=nd - 1, offset=qm + 17))
        p = p2
    nd_arr = np.array(nds, np.int32)
    na_arr = np.array(nas, np.int32)
    out = os.path.join(A.TMP, f"{die}_rt_tpl.npz")
    np.savez(out, pos=np.array(pos, np.int64), na=na_arr, nd=nd_arr,
             flag=np.array(flags, np.int8),
             deltas=np.concatenate(deltas) if deltas else np.zeros(0, np.int32),
             doff=np.concatenate([[0], np.cumsum(np.maximum(nd_arr - 1, 0), dtype=np.int64)[:-1]]),
             attrs=np.concatenate(attrs) if attrs else np.zeros(0, np.uint16),
             aoff=np.concatenate([[0], np.cumsum(na_arr, dtype=np.int64)[:-1]]),
             gaps=np.array(gaps, np.int64).reshape(-1, 2))
    log.info("%s: %d templates (attrs %d, fan-out entries %d), %d unparsed stretches (%d bytes), -> %s",
             die, len(pos), int(na_arr.sum()), int(nd_arr.sum()), len(gaps),
             int(sum(g[1] for g in gaps)), out)


N_TPL = {"stingray4": 197688}            # DYGR_ROUTE_ELEMENT_TEMPLATE count (zlib-trailer type table)
N_EDGE = {"stingray4": 3612712}          # int / unsigned short payload count (type table)


def fanout(die):
    """EXACT decode of node -> fan-out from the PDB serializers in libddb_dygr.so
    (schemas: scripts/cycloneiv_ddb_symdump.py; docs/altera/cycloneIV/cycloneiv-ddb-format.md).

    - Element row (offset 16, 12 B) = DYGR_ROUTE_ELEMENT: i16 d(m_x), i16 d(m_y),
      i32 d(first fan-out dest id V), i32 ptr tag for m_template
      (tag 0 = NULL, 4 = new registry object, (d<<2)|2 = registry index += d).
    - Template pool = last deferred-object pool, ends at EOF; per template:
      5 x i16 + 3 x i8 field deltas vs the previous template, u16 count,
      count x i32 offset deltas (elem0 chains to the previous template's offs[0]),
      u16 count again, count x u16 position deltas (same chaining).
    - dests(elem) = V + offs[]  (DYGR_ROUTE_ELEMENT::add_fanout stores dest - first_dest).
    -> <die>_rt_fanout.npz."""
    raw = body(die)
    L = len(raw)
    n_tpl, n_edge = N_TPL[die], N_EDGE[die]
    n = struct.unpack_from("<I", raw, 12)[0]

    # -- element table: template ptr-tag chain + V cumsum
    rec = np.frombuffer(raw, NODE, count=n, offset=16)
    Vraw = np.cumsum(rec["c"].astype(np.int64)).astype(np.int32)  # i32 wraparound = xfr_int_delta
    vflag = Vraw < 0                      # bit 31 = has-fanout flag
    V = (Vraw.astype(np.int64) & 0x7fffffff).astype(np.int32)  # FIRST fan-out dest id; 0 = none
    tags = rec["dn"]
    tpl = np.full(n, -1, np.int32)
    # Registry slots start at 1; a NEW object (tag 12) takes the next slot WITHOUT moving the
    # delta cursor; a reference tag (d<<2)|2 moves the cursor by d.  0-based id = slot - 1.
    last, nxt = 0, 1
    bad = 0
    for i, t in enumerate(tags.tolist()):
        if t == 0:
            continue
        if t == 12:
            tpl[i] = nxt - 1
            nxt += 1
        elif t & 3 == 2:
            last += t >> 2
            tpl[i] = last - 1
        else:
            bad += 1
    if bad or nxt - 1 != n_tpl:
        raise dd.DdbError(f"template ptr-tag chain: {bad} bad tags, {nxt - 1} new objects (want {n_tpl})")

    # -- template-vector cross-check (follows the element list): first tag jumps back to
    #    registry object 0, then +1 per entry: (d<<2)|2 encoding.
    p = 16 + 12 * n
    cnt = struct.unpack_from("<I", raw, p)[0]
    t0, t1 = struct.unpack_from("<ii", raw, p + 4)
    if cnt != n_tpl or t0 != ((1 - last) << 2 | 2) or t1 != 6:
        raise dd.DdbError(f"template vector check failed: cnt {cnt}, tags {t0} {t1} (last={last})")

    # -- template pool: fixed total size 17 B/template + 6 B/edge, ends at EOF
    start = L - (17 * n_tpl + 6 * n_edge)
    p = start
    enum = np.zeros(n_tpl, np.uint16); nedg = np.zeros(n_tpl, np.uint16)
    zz = np.zeros(n_tpl, np.int16); idx = np.zeros(n_tpl, np.int16)
    redund = np.zeros(n_tpl, np.uint16); leng = np.zeros(n_tpl, np.uint8)
    metal = np.zeros(n_tpl, np.uint8); direc = np.zeros(n_tpl, np.uint8)
    cnts = np.zeros(n_tpl, np.int32)
    offs_all, poss_all = [], []
    s_en = s_ne = s_z = s_ix = s_rd = s_ln = s_mt = s_dr = 0
    prev_off0, prev_pos0 = 0, 0
    sc = struct.Struct("<hhhhhbbbH")
    for k in range(n_tpl):
        d_en, d_ne, d_z, d_ix, d_rd, d_ln, d_mt, d_dr, c1 = sc.unpack_from(raw, p)
        p += 15
        s_en = (s_en + d_en) & 0xffff; s_ne = (s_ne + d_ne) & 0xffff
        s_z = (s_z + d_z) & 0xffff; s_ix = (s_ix + d_ix) & 0xffff
        s_rd = (s_rd + d_rd) & 0xffff; s_ln = (s_ln + d_ln) & 0xff
        s_mt = (s_mt + d_mt) & 0xf; s_dr = (s_dr + d_dr) & 0xf
        if c1 != s_ne:
            raise dd.DdbError(f"template {k} at {p - 15}: count {c1} != m_num_edges {s_ne}")
        if c1:
            d = np.frombuffer(raw, "<i4", count=c1, offset=p)
            p += 4 * c1
            o = np.cumsum(d.astype(np.int64)).astype(np.int32)
            o += prev_off0
            prev_off0 = int(o[0])
            offs_all.append(o)
        else:
            prev_off0 = 0
        c2 = struct.unpack_from("<H", raw, p)[0]
        p += 2
        if c2 != c1:
            raise dd.DdbError(f"template {k}: second count {c2} != {c1}")
        if c1:
            d = np.frombuffer(raw, "<u2", count=c1, offset=p)
            p += 2 * c1
            q = np.cumsum(d.astype(np.uint64)).astype(np.uint16)
            q += prev_pos0
            prev_pos0 = int(q[0])
            poss_all.append(q)
        else:
            prev_pos0 = 0
        enum[k], nedg[k], zz[k], idx[k] = s_en, s_ne, s_z, s_ix
        redund[k], leng[k], metal[k], direc[k] = s_rd, s_ln, s_mt, s_dr
        cnts[k] = c1
    if p != L:
        raise dd.DdbError(f"template pool ended at {p}, EOF {L}")
    if int(cnts.sum()) != n_edge:
        raise dd.DdbError(f"edge total {int(cnts.sum())} != type table {n_edge}")
    offs = np.concatenate(offs_all) if offs_all else np.zeros(0, np.int32)
    poss = np.concatenate(poss_all) if poss_all else np.zeros(0, np.uint16)
    eoff = np.zeros(n_tpl, np.int64)
    np.cumsum(cnts[:-1], dtype=np.int64, out=eoff[1:])

    # -- consistency: V == 0 exactly where the template is empty; expansions in range
    first = offs[eoff[cnts > 0]]
    nonzero_first = int((first != 0).sum())
    ecnt = cnts[tpl]                      # per-element edge count
    v0_mismatch = int(((V == 0) != (ecnt == 0)).sum())
    # -- expand (dests = V + offs: DYGR_ROUTE_ELEMENT::add_fanout stores dest - first_dest and
    #    the element keeps the first dest) and PROVE the decode by inverting it against the
    #    FANIN_MAP: inverted per-node fan-in counts must equal m_num_fanin_edges for ALL nodes.
    has = V > 0
    reps = cnts[tpl[has]].astype(np.int64)
    srcs = np.repeat(np.flatnonzero(has), reps)
    pick = np.repeat(eoff[tpl[has]], reps) + (np.arange(len(srcs)) - np.repeat(np.cumsum(reps) - reps, reps))
    dsts = np.repeat(V[has].astype(np.int64), reps) + offs[pick]
    if dsts.min() < 0 or dsts.max() >= n:
        raise dd.DdbError(f"expanded dests out of range: {dsts.min()}..{dsts.max()}")
    fin_cnt = np.bincount(dsts, minlength=n)
    nd_sec = np.frombuffer(raw, "<i4", count=3 * n, offset=TWIN_OFF[die]).reshape(n, 3)
    f1 = np.cumsum(nd_sec[:, 1].astype(np.int64)).astype(np.int32)
    inv_bad = int((fin_cnt != f1).sum())
    if inv_bad:
        raise dd.DdbError(f"fan-in inversion: {inv_bad} nodes with inverted count != m_num_fanin_edges")
    out = os.path.join(A.TMP, f"{die}_rt_fanout.npz")
    np.savez(out, x=np.cumsum(rec["dx"]).astype(np.int16), y=np.cumsum(rec["dy"]).astype(np.int16),
             V=V, vflag=vflag, tpl=tpl, enum=enum, nedges=nedg, z=zz, index=idx, redund=redund,
             length=leng, metal=metal, direction=direc, cnt=cnts, eoff=eoff, offs=offs, poss=poss,
             pool_start=np.int64(start))
    log.info("%s: EXACT fan-out decode: %d elements (%d with fan-out, %d without, V-vs-empty "
             "mismatches %d), %d templates (pool %d..%d), %d template edges -> %d graph edges; "
             "offs[0]!=0 for %d templates; dest range %d..%d (N=%d); fan-in inversion PASS "
             "(all %d nodes); -> %s",
             die, n, int(has.sum()), int((V == 0).sum()), v0_mismatch,
             n_tpl, start, L, int(cnts.sum()), len(dsts), nonzero_first,
             int(dsts.min()), int(dsts.max()), n, n, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("nodes", "twin", "templates", "fanout"))
    ap.add_argument("--die", default="stingray4")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_ddb_routing.log"))])
    if a.cmd == "nodes":
        nodes(a.die)
    elif a.cmd == "twin":
        twin(a.die)
    elif a.cmd == "templates":
        templates(a.die)
    elif a.cmd == "fanout":
        fanout(a.die)


if __name__ == "__main__":
    main()
