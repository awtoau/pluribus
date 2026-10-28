#!/usr/bin/env python3.15t
"""Cyclone IV GX `routing.ddb`: node table, wire-endpoint (twin) map, fan-out templates.

Format: docs/cycloneiv-ddb-format.md "routing.ddb".  Body sections (byte offsets for stingray4):
- 16..16+12N          node table: N x (i16 dx, i16 dy, i32 c, i32 dn); cumsum(dx, dy) = tile,
                      cumsum(dn) = entry offset of the node's fan-out list (2 units per fan-out)
                      in the IN-MEMORY expanded arrays (not byte-addressable in the file), c = a
                      delta-coded per-node reference (semantics open, see doc).
- 22,469,513          u32 N, then N x 12 bytes (i32 delta-coded twin id+1, i32, i32): the wire's
                      OTHER-END record (H4R90C119RT[0] -> H4R90C112LT[0]); 0 = none (every LE).
- 63,120,855..        fan-out TEMPLATE stream: [u32 na][na x u16 attrs][i16 e][u32 0][i16 e]
                      [i8 flag][u16][u32 nd][u16 first=0][(nd-1) x i32 deltas], e == nd - na;
                      dests of a node r using the template = r + cumsum(0, deltas).
Delta streams restart where the value is < -2^30 (restart value = v + 2^31); ids stored +1, 0 = NULL.

  python3.15t scripts/cycloneiv_ddb_routing.py nodes     [--die stingray4]  # -> tmp/ddb/<die>_rt_nodes.npy
  python3.15t scripts/cycloneiv_ddb_routing.py twin      [--die stingray4]  # -> <die>_rt_twin.npy + name check
  python3.15t scripts/cycloneiv_ddb_routing.py templates [--die stingray4]  # -> <die>_rt_tpl.npz
Streams the body; peak RSS ~0.5 GB.  Log tmp/logs/cycloneiv_ddb_routing.log.
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("nodes", "twin", "templates"))
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


if __name__ == "__main__":
    main()
