#!/usr/bin/env python3.15t
"""Cyclone IV GX routing decode from the Quartus asm.ddb (exact tables), scored against the RCF oracle.

Semantics (docs/cycloneiv-ddb-format.md): record = one routing wire (vendor name from icname.ddb);
group = one destination mux the wire feeds; entry (position, b0, b1) = one CRAM bit of that mux:
  b0 = +1  the one-hot select bit of this input (always programmed 1)
  b0 = -1 / 0  the two shared second-level bits of the mux; programmed 1 iff b1 == -1
  asm (frame, v) -> plane (FX + 17 - (frame - FX), 6344 - v), FX = base frame of the LAB column.
A mux ("block") = the groups that share the same second-level bit positions; the plane selects
input g of a block iff g's programmed bits are set and every other bit of the block is clear.

  python3.15t scripts/cycloneiv_asm_decode.py prepare                       # tmp/ddb/<die>_dec_*.npy
  python3.15t scripts/cycloneiv_asm_decode.py learn --designs 'gx150_sp_*' --split even
  python3.15t scripts/cycloneiv_asm_decode.py score --designs 'gx150_sp_*' --split odd
Log tmp/logs/cycloneiv_asm_decode.log.  Peak RSS ~3 GB (prepare), ~2.5 GB (score).
"""
import argparse
import collections
import json
import logging
import os
import pickle
import re
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_ddb_asm as A  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_asm_decode")
DIE = "stingray4"
FRAME_MIRROR = 17      # plane offset k within a LAB column <-> asm offset 17 - k
ROW_MIRROR = 6344      # plane v <-> asm 6344 - v
NAME = re.compile(r"^(H4|V4|H24|V16)(?:R(\d+)C(\d+)|_C(\d+)(UP|DN)_R|R(\d+)_(RT|LT)_C)(RT|LT|UP|DN)?\[(\d+)\]$")
DEC = os.path.join(A.TMP, f"{DIE}_dec")


def icnames(die=DIE):
    """record id -> vendor name (first icname table; ids start at the header's base id, deltas of 1)."""
    import struct
    import cyclonev_ddb_decode as dd
    path = f"{A.DEVINFO}/ddb_{die}_icname.ddb"
    body = b"".join(dd.iter_body(path))
    ver, n, base = struct.unpack_from("<III", body, 0)
    base &= 0x7FFFFFFF
    p, out, nid = 12, {}, base
    for i in range(n):
        ln, = struct.unpack_from("<I", body, p)
        s = body[p + 4:p + 4 + ln].decode("ascii", "replace")
        v, = struct.unpack_from("<I", body, p + 4 + ln)
        p += 8 + ln
        nid = (v & 0x7FFFFFFF) if v & 0x80000000 else nid + v if i else base
        out[nid] = s
    return out


def asm_to_plane(fa, va, fxs):
    """asm (frame, v) arrays -> plane (frame, v): frame mirrored inside its LAB column, v mirrored over the die."""
    fa, va = np.asarray(fa, np.int64), np.asarray(va, np.int64)
    i = np.searchsorted(fxs, fa, "right") - 1
    FX = fxs[np.clip(i, 0, len(fxs) - 1)]
    return (FX + FRAME_MIRROR - (fa - FX)).astype(np.int32), (ROW_MIRROR - va).astype(np.int32)


def programmed(b0, b1):
    """Which entries of a group are programmed 1: the select bit, and a second-level bit iff b1 == -1."""
    return (np.asarray(b0) == 1) | (np.asarray(b1) == -1)


def prepare():
    a = A.load(DIE)
    pos, flag = np.asarray(a["pos"]), np.asarray(a["flag"])
    gsize, grec, gstart = A.group_sizes(a)
    gid = np.repeat(np.arange(len(gsize), dtype=np.int32), gsize)
    b0 = (flag & 0xFF).astype(np.int8)
    b1 = ((flag >> 8) & 0xFF).astype(np.int8)
    g = cg.load("ep4cgx150")
    fxs = np.array(sorted(g.FX[x] for x in g.FX), np.int64)
    pf, pv = asm_to_plane(pos % 6154, pos // 6154, fxs)
    pred = programmed(b0, b1)
    # block key: the non-select entries of the group (positions as plane linear address), up to 2
    lin = pf.astype(np.int64) * 6368 + pv
    isA = b0 != 1
    key = np.full((len(gsize), 2), -1, np.int64)
    # first and second A entries per group
    order = np.lexsort((lin, gid))
    gid_o, lin_o, isA_o = gid[order], lin[order], isA[order]
    sel = isA_o
    g_a, l_a = gid_o[sel], lin_o[sel]
    first = np.concatenate([[True], g_a[1:] != g_a[:-1]])
    key[g_a[first], 0] = l_a[first]
    idx_first = np.flatnonzero(first)
    second = idx_first + 1
    ok = (second < len(g_a))
    ok[ok] &= g_a[second[ok]] == g_a[idx_first[ok]]
    key[g_a[second[ok]], 1] = l_a[second[ok]]
    noA = key[:, 0] < 0           # groups without non-select entries: key on their own first position
    key[noA, 0] = lin[gstart[noA]]
    _, block = np.unique(key, axis=0, return_inverse=True)
    block = block.astype(np.int32).reshape(-1)
    # entry -> unique (block, position) id: a bit may appear in several groups of one block
    u, inv = np.unique(block[gid].astype(np.int64) << 32 | (lin & 0xFFFFFFFF), return_inverse=True)
    e_ukey, ukey_block = inv.astype(np.int32), (u >> 32).astype(np.int32)
    os.makedirs(A.TMP, exist_ok=True)
    for name, arr in (("pf", pf), ("pv", pv), ("pred", pred), ("gid", gid), ("grec", grec), ("gstart", gstart),
                      ("gsize", gsize), ("block", block), ("b0", b0), ("e_ukey", e_ukey), ("ukey_block", ukey_block)):
        np.save(f"{DEC}_{name}.npy", arr)
    names = icnames()
    pickle.dump(names, open(f"{DEC}_names.pkl", "wb"))
    log.info("prepared: %d entries, %d groups, %d blocks, %d named records", len(pos), len(gsize), block.max() + 1, len(names))


class Dec:
    def __init__(self):
        self.pf = np.load(f"{DEC}_pf.npy", mmap_mode="r")
        self.pv = np.load(f"{DEC}_pv.npy", mmap_mode="r")
        self.pred = np.load(f"{DEC}_pred.npy")
        self.gid = np.load(f"{DEC}_gid.npy", mmap_mode="r")
        self.grec = np.load(f"{DEC}_grec.npy")
        self.gstart = np.load(f"{DEC}_gstart.npy")
        self.gsize = np.load(f"{DEC}_gsize.npy")
        self.block = np.load(f"{DEC}_block.npy")
        self.b0 = np.load(f"{DEC}_b0.npy", mmap_mode="r")
        self.names = pickle.load(open(f"{DEC}_names.pkl", "rb"))
        self.g = cg.load("ep4cgx150")
        self.fxs = np.array(sorted(self.g.FX[x] for x in self.g.FX), np.int64)
        self.xs_sorted = sorted(self.g.FX, key=lambda x: self.g.FX[x])
        ng = len(self.gsize)
        gid = np.asarray(self.gid)
        self.npred = np.bincount(gid[self.pred], minlength=ng).astype(np.int32)
        self.e_ukey = np.load(f"{DEC}_e_ukey.npy", mmap_mode="r")
        self.ukey_block = np.load(f"{DEC}_ukey_block.npy")
        self.nblocks = int(self.block.max()) + 1

    def active(self, plane):
        """Groups selected by a design: predicted bits all set, every other bit of the block clear.
        -> (group ids, record ids, block ids).  Integer bincounts over the set entries only (no float
        weight copies of the 51 M-entry arrays)."""
        s = np.flatnonzero(plane.has(np.asarray(self.pf), np.asarray(self.pv)))
        gid = np.asarray(self.gid)
        sp = s[self.pred[s]]
        nset_pred = np.bincount(gid[sp], minlength=len(self.gsize))
        bset = np.bincount(self.ukey_block[np.unique(self.e_ukey[s])], minlength=self.nblocks)
        act = (self.npred > 0) & (nset_pred == self.npred) & (bset[self.block] == self.npred)
        gids = np.flatnonzero(act)
        return gids, self.grec[gids], self.block[gids]

    def col_of(self, f):
        """Plane column x whose frame range holds frame f."""
        i = int(np.searchsorted(self.fxs, f, "right") - 1)
        return self.xs_sorted[max(i, 0)]


def vendor_parse(nm):
    m = NAME.match(nm)
    if not m:
        return None
    typ, R, C, C2, d2, R2, d3, d, k = m.groups()
    if typ in ("H4", "V4"):
        return (typ, d, int(k), int(R), int(C))
    if typ == "V16":
        return (typ, d2, int(k), None, int(C2))
    return (typ, d3, int(k), int(R2), None)


def src_name(rec, names, nmap):
    """RCF source key (type, s, i, x, y) of a record via the learned vendor->RCF map, or None."""
    nm = names.get(rec)
    if nm is None:
        return None
    p = vendor_parse(nm)
    if p is None:
        return None
    typ, d, k, R, C = p
    rule = nmap.get(f"{typ}|{d}")
    if rule is None:
        return None
    rt, roff, coff, imap = rule
    i = imap.get(str(k))
    if i is None or R is None or C is None:
        return None
    return (rt, 0, i, C - coff, roff - R)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("prepare", "learn", "score"))
    ap.add_argument("--designs", default="gx150_sp_*")
    ap.add_argument("--split", default="all")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_asm_decode.log"))])
    if a.cmd == "prepare":
        prepare()
        return
    import cycloneiv_asm_tables as T
    names = [n for n in cc.designs(a.designs) if rl.split_of(n, a.split)]
    if a.limit:
        names = names[:a.limit]
    dec = Dec()
    if a.cmd == "learn":
        T.learn(dec, names)
    else:
        T.score(dec, names)


if __name__ == "__main__":
    main()
