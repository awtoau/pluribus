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
import fastops  # noqa: E402
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


V_COL = re.compile(r"^(?:V4R\d+C(\d+)(?:UP|DN)|V16_C(\d+)(?:UP|DN)_R)\[")
AFX_MIN_VOTES = 1000     # V4/V16 entries at the peak before a derived AFX is trusted
MAX_OFF = 17             # asm band width: offsets 0..17 inside a column (plane offsets 0..+17)


def afx_map(g, grec, gid, fa, names):
    """Data-driven asm-side column bases.  The asm frame axis lays columns out differently around
    M9K / MUL / IO columns: 7 LAB columns of EP4CGX150 sit inside the plane's M9K frame spans, so
    AFX != FX there and the old FX-based mirror mapped them nowhere (issue #141 specimen finding).
    A V4 / V16 record's destination muxes live in its own column (vendor C = fitter x + 2); the
    per-column fa histogram of those entries peaks at a fixed band offset, so AFX = peak - that
    offset.  The offset itself is the die-wide MODE of (peak - FX) over LAB columns: most columns
    are already correctly placed by FX (validated against the corpus), so the mode is the true
    peak offset and only the outlier columns move.
    -> {x: AFX}, defaulting to FX where there is no V4/V16 evidence."""
    nrec = int(grec.max()) + 1
    x_of_rec = np.full(nrec, -1, np.int16)
    for r, nm in names.items():
        m = V_COL.match(nm)
        if m and r < nrec:
            x_of_rec[r] = int(m.group(1) or m.group(2)) - 2
    ex = x_of_rec[grec[gid]]
    m = (ex >= 0) & (ex <= g.xmax)
    packed = ex[m].astype(np.int64) * 6154 + fa[m]
    u, c = fastops.unique_counts(packed)
    ux, ufa = (u // 6154).astype(np.int32), (u % 6154).astype(np.int32)
    afx = {x: g.FX[x] for x in g.FX}
    peaks = {}
    for x in fastops.unique(ux).tolist():
        sel = np.flatnonzero(ux == x)
        best = int(np.argmax(c[sel]))
        if c[sel][best] >= AFX_MIN_VOTES:
            peaks[int(x)] = (int(ufa[sel][best]), int(c[sel][best]))
    mode = collections.Counter(p - g.FX[x] for x, (p, _n) in peaks.items() if g.kind.get(x) == "LAB").most_common(1)
    if not mode:
        db_die("no LAB column peaks for the AFX mode")
    off = mode[0][0]
    log.info("AFX peak offset (die-wide mode over LAB columns): %d (%d columns)", off, mode[0][1])
    moved = []
    for x, (p, votes) in peaks.items():
        base = p - off
        if base != afx[x]:
            moved.append((x, afx[x], base, votes))
        afx[x] = base
    for x, old, new, votes in sorted(moved):
        log.info("AFX column %d: %s -> %d (%d votes at peak)", x, old, new, votes)
    vals = collections.Counter(afx.values())
    dup = {v: n for v, n in vals.items() if n > 1}
    if dup:
        db_die(f"derived AFX collide: {dup}")
    return afx


def db_die(msg):
    log.error(msg)
    raise SystemExit(msg)


DROP_F = 30000           # plane frame for out-of-band entries: beyond any plane, never set, keys positive


def asm_to_plane_afx(fa, va, g, afx):
    """asm (frame, v) -> plane (frame, v) using per-column asm bases.  Entries outside any band's
    valid offset range (0..MAX_OFF: M9K bulk, interface extras) get plane frame DROP_F: never fire."""
    fa, va = np.asarray(fa, np.int64), np.asarray(va, np.int64)
    cols = sorted(afx, key=lambda x: afx[x])
    bases = np.array([afx[x] for x in cols], np.int64)
    pfx = np.array([g.FX[x] for x in cols], np.int64)
    i = np.clip(np.searchsorted(bases, fa, "right") - 1, 0, len(bases) - 1)
    off = fa - bases[i]
    pf = np.where((off >= 0) & (off <= MAX_OFF), pfx[i] + FRAME_MIRROR - off, DROP_F)
    return pf.astype(np.int32), (ROW_MIRROR - va).astype(np.int32)


def programmed(b0, b1, first=None):
    """Which entries of a group are programmed 1: the select bit (the group's first entry; b0 = +1, or 0 on
    ~3 % of the 3-groups), and a second-level bit iff b1 == -1."""
    p = (np.asarray(b0) == 1) | (np.asarray(b1) == -1)
    if first is not None:
        p = p | np.asarray(first)
    return p


def prepare():
    a = A.load(DIE)
    pos, flag = np.asarray(a["pos"]), np.asarray(a["flag"])
    gsize, grec, gstart = A.group_sizes(a)
    gid = np.repeat(np.arange(len(gsize), dtype=np.int32), gsize)
    b0 = (flag & 0xFF).astype(np.int8)
    b1 = ((flag >> 8) & 0xFF).astype(np.int8)
    g = cg.load("ep4cgx150")
    names = icnames()
    fa = (pos % 6154).astype(np.int64)
    afx = afx_map(g, np.asarray(grec), gid, fa, names)
    pf, pv = asm_to_plane_afx(fa, pos // 6154, g, afx)
    log.info("entries outside any band (dropped, never fire): %d / %d", int((pf == DROP_F).sum()), len(pf))
    first = np.zeros(len(pos), bool)
    first[gstart[gsize == 3]] = True          # the select entry of every 3-group (b0 = 0 on some)
    pred = programmed(b0, b1, first)
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
    _, block = fastops.unique_rows2_inverse(key)
    block = block.astype(np.int32)
    # entry -> unique (block, position) id: a bit may appear in several groups of one block
    u, inv = fastops.unique_inverse(block[gid].astype(np.int64) << 32 | (lin & 0xFFFFFFFF))
    e_ukey, ukey_block = inv.astype(np.int32), (u >> 32).astype(np.int32)
    os.makedirs(A.TMP, exist_ok=True)
    for name, arr in (("pf", pf), ("pv", pv), ("pred", pred), ("gid", gid), ("grec", grec), ("gstart", gstart),
                      ("gsize", gsize), ("block", block), ("b0", b0), ("e_ukey", e_ukey), ("ukey_block", ukey_block)):
        np.save(f"{DEC}_{name}.npy", arr)
    json.dump(afx, open(f"{DEC}_afx.json", "w"))
    pickle.dump(names, open(f"{DEC}_names.pkl", "wb"))
    log.info("prepared: %d entries, %d groups, %d blocks, %d named records", len(pos), len(gsize), block.max() + 1, len(names))


class Dec:
    """Per-die asm tables.  Every array is np.load(mmap_mode='r'): file-backed pages are shared by all
    threads and processes through the page cache and are reclaimable (anonymous copies were ~0.5 GB
    per Dec).  `names` (1.5 M-entry dict, 120 MB) loads on first use."""

    def __init__(self):
        mm = {"mmap_mode": "r"}
        self.pf = np.load(f"{DEC}_pf.npy", **mm)
        self.pv = np.load(f"{DEC}_pv.npy", **mm)
        self.pred = np.load(f"{DEC}_pred.npy", **mm)
        self.gid = np.load(f"{DEC}_gid.npy", **mm)
        self.grec = np.load(f"{DEC}_grec.npy", **mm)
        self.gstart = np.load(f"{DEC}_gstart.npy", **mm)
        self.gsize = np.load(f"{DEC}_gsize.npy", **mm)
        self.block = np.load(f"{DEC}_block.npy", **mm)
        self.b0 = np.load(f"{DEC}_b0.npy", **mm)
        self.g = cg.load("ep4cgx150")
        self.fxs = np.array(sorted(self.g.FX[x] for x in self.g.FX), np.int64)
        self.xs_sorted = sorted(self.g.FX, key=lambda x: self.g.FX[x])
        ng = len(self.gsize)
        gid = np.asarray(self.gid)
        self.npred = np.bincount(gid[self.pred], minlength=ng).astype(np.int32)
        self.e_ukey = np.load(f"{DEC}_e_ukey.npy", **mm)
        self.ukey_block = np.load(f"{DEC}_ukey_block.npy", **mm)
        self.nblocks = int(self.block.max()) + 1

    @property
    def names(self):
        n = self.__dict__.get("_names")
        if n is None:
            with open(f"{DEC}_names.pkl", "rb") as fh:
                self._names = n = pickle.load(fh)
        return n

    def _flat(self, plane):
        """Plane-independent gather index of every asm entry (dense-bitmap slot); 51 M int32.  Derived
        artifact cached beside the tables and mmapped (shared by all processes); built once per plane shape."""
        c = self.__dict__.get("_flat_cache")
        if c is None or c[0] != plane.shape:
            path = f"{DEC}_flat_{plane.shape[0]}x{plane.shape[1]}.npy"
            try:
                fl = np.load(path, mmap_mode="r")
                if fl.shape != self.pf.shape:
                    raise FileNotFoundError(path)
            except (FileNotFoundError, ValueError, OSError):
                fl = plane.flat_index(np.asarray(self.pf), np.asarray(self.pv))
                tmp = f"{path}.{os.getpid()}.tmp"
                with open(tmp, "wb") as fh:
                    np.save(fh, fl)
                os.replace(tmp, path)
                del fl
                fl = np.load(path, mmap_mode="r")
            self._flat_cache = c = (plane.shape, fl)
        return c[1]

    def active(self, plane, method=None):
        """Groups selected by a design: predicted bits all set, every other bit of the block clear.
        -> (group ids, record ids, block ids).  Integer bincounts over the set entries only (no float
        weight copies of the 51 M-entry arrays); counts are cast to int32 (<= 16 per group) so the
        per-group temporaries are 4 B, not 8 B.
        method: "dense" (default; bitmap gather + mark array) | "legacy" (searchsorted + np.unique);
        env PLURIBUS_ACTIVE.  Identical results (docs/perf-pass.md)."""
        method = method or os.environ.get("PLURIBUS_ACTIVE", "dense")
        if method == "dense":
            s = np.flatnonzero(plane.dense()[self._flat(plane)])
        else:
            s = np.flatnonzero(plane._has_searchsorted(np.asarray(self.pf), np.asarray(self.pv)))
        gid = np.asarray(self.gid)
        sp = s[self.pred[s]]
        nset_pred = np.bincount(gid[sp], minlength=len(self.gsize)).astype(np.int32)
        uk = fastops.mark_unique(self.e_ukey[s], len(self.ukey_block)) if method == "dense" else fastops.unique(self.e_ukey[s])
        bset = np.bincount(self.ukey_block[uk], minlength=self.nblocks).astype(np.int32)
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
