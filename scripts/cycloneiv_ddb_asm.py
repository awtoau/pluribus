#!/usr/bin/env python3.15t
"""Cyclone IV GX `asm.ddb` (Quartus route-assembler database) reader.

Same record family as Cyclone V (docs/altera/cycloneV/cyclonev-ddb-format.md; type table DYGR_ROUTE_ASM_NODE /
unsigned short / DYGR_ROUTE_ASM_BIT, identical layout crcs).  Format: docs/cycloneiv-ddb-format.md.

  python3.15t scripts/cycloneiv_ddb_asm.py parse [--die stingray4]   # asm.ddb -> tmp/ddb/<die>_asm_*.npy
  python3.15t scripts/cycloneiv_ddb_asm.py stats [--die stingray4]   # shapes / vals / flag / trailer histograms
Peak RSS < 1.5 GB (one int32 array per bit field).  Log tmp/logs/cycloneiv_ddb_asm.log.
"""
import argparse
import collections
import logging
import os
import struct
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_ddb_decode as dd  # noqa: E402

log = logging.getLogger("cycloneiv_ddb_asm")
DEVINFO = dd.DEVINFO + "/cycloneivgx"
TMP = os.path.join(REPO, "tmp", "ddb")
# CRAM address space of the die: frame (fastest) + FRAMES * bit; FRAMES = 6154 data frames (EP4CGX150)
FRAMES = {"stingray4": 6154}
FRAME_BITS = {"stingray4": 796 * 8}


def asm_path(die):
    return f"{DEVINFO}/ddb_{die}_asm.ddb"


def parse(die):
    """Stream the body once; write per-bit and per-record arrays to tmp/ddb/<die>_asm_*.npy.
    bit arrays: pos (int64 running sum of deltas, over ALL records), flag (int32), rec (int32 record id)
    record arrays: n, nb (int32), voff (int64 offset into vals), vals (uint16), lead (int32, the i32 that
    opens each record; the Cyclone V reader took it as the previous record's trailer)."""
    path = asm_path(die)
    hdr = dd.read_header(path)
    types = {t[5]: t[3] for t in dd.read_types(path, hdr)}
    n_nodes, n_ush, n_bits = types["DYGR_ROUTE_ASM_NODE"], types["unsigned short"], types["DYGR_ROUTE_ASM_BIT"]
    bit_delta = np.zeros(n_bits, np.int32)
    bit_flag = np.zeros(n_bits, np.int32)
    rec_n = np.zeros(n_nodes, np.int32)
    rec_nb = np.zeros(n_nodes, np.int32)
    rec_tr = np.zeros(n_nodes, np.int32)
    vals = np.zeros(n_ush, np.uint16)
    blocks = dd.iter_body(path, hdr)
    buf = bytearray()
    eof = False

    def fill(need):
        nonlocal eof
        while len(buf) < need and not eof:
            try:
                buf.extend(next(blocks))
            except StopIteration:
                eof = True

    fill(12)
    ver, n1, n2 = struct.unpack_from("<III", buf, 0)
    if ver != 4 or n1 != n2 or n1 != n_nodes:
        raise dd.DdbError(f"asm body header {ver},{n1},{n2} vs type table {n_nodes}")
    del buf[:12]
    unp = struct.unpack_from
    bi = vi = 0
    t0 = time.time()
    done = 0
    while done < n1:
        fill(1 << 20)
        if eof and len(buf) < 8:
            if any(buf):
                raise dd.DdbError("truncated record")
            break
        # parse as many whole records as the buffer holds: i32 lead, u16 n, n x u16, u16 nb, nb x (i32, i32)
        p = 0
        L = len(buf)
        while done < n1:
            if p + 8 > L:
                break
            n, = unp("<H", buf, p + 4)
            if p + 8 + 2 * n > L:
                break
            nb, = unp("<H", buf, p + 6 + 2 * n)
            size = 8 + 2 * n + 8 * nb
            if p + size > L:
                break
            rec_n[done], rec_nb[done] = n, nb
            rec_tr[done] = unp("<i", buf, p)[0]
            if n:   # bytes(): a frombuffer view would pin the bytearray (no del buf[:p])
                vals[vi:vi + n] = np.frombuffer(bytes(buf[p + 6:p + 6 + 2 * n]), "<u2")
                vi += n
            if nb:
                a = np.frombuffer(bytes(buf[p + 8 + 2 * n:p + size]), "<i4").reshape(nb, 2)
                bit_delta[bi:bi + nb] = a[:, 0]
                bit_flag[bi:bi + nb] = a[:, 1]
                bi += nb
            p += size
            done += 1
        if p == 0 and not eof:
            fill(len(buf) + (1 << 20))
            continue
        if p == 0 and eof:
            if any(buf):
                raise dd.DdbError(f"{len(buf)} unparsed bytes after {done} records")
            break
        del buf[:p]


    fill(8)
    if any(buf):
        raise dd.DdbError(f"{len(buf)} unparsed bytes after {done} records")
    if bi != n_bits or vi != n_ush:
        raise dd.DdbError(f"bits {bi} vs type table {n_bits}; ushorts {vi} vs {n_ush}")
    if done != n1:
        raise dd.DdbError(f"{done} records parsed, header says {n1}")
    log.info("%s: %d records, %d bits, %d ushorts, parse ends at EOF, %.0fs", die, done, bi, vi, time.time() - t0)
    os.makedirs(TMP, exist_ok=True)
    rec = np.repeat(np.arange(n_nodes, dtype=np.int32), rec_nb)
    pos = np.cumsum(bit_delta, dtype=np.int64)
    voff = np.concatenate([[0], np.cumsum(rec_n, dtype=np.int64)[:-1]])
    for name, arr in (("pos", pos), ("flag", bit_flag), ("rec", rec), ("n", rec_n), ("nb", rec_nb),
                      ("voff", voff), ("vals", vals), ("lead", rec_tr)):
        np.save(os.path.join(TMP, f"{die}_asm_{name}.npy"), arr)
    log.info("%s: wrote %s/%s_asm_*.npy; running sum range %d..%d", die, TMP, die, pos.min(), pos.max())


def load(die, names=("pos", "flag", "rec", "n", "nb", "voff", "vals", "lead")):
    return {k: np.load(os.path.join(TMP, f"{die}_asm_{k}.npy"), mmap_mode="r") for k in names}


def group_sizes(a):
    """Per record the fanout-group sizes: vals[1:] + [nb - sum(vals[1:])] (the LAST group's size is implicit;
    vals[0] is a flag).  -> (gsize int32 per group, grec int32 record of each group, gstart int64 first bit)."""
    n, nb, vals, voff = a["n"], a["nb"], np.asarray(a["vals"], np.int64), a["voff"]
    nz = n > 0
    rest = np.ones(len(vals), bool)
    rest[voff[nz]] = False                  # drop vals[0] (a flag)
    ngroups = np.where(nz, n, 1)            # n - 1 explicit + 1 implicit; empty records: 1 empty group
    grec = np.repeat(np.arange(len(n), dtype=np.int32), ngroups)
    gsize = np.zeros(int(ngroups.sum()), np.int32)
    last = np.cumsum(ngroups) - 1
    s = np.zeros(len(n), np.int64)
    s[nz] = np.add.reduceat(vals, voff[nz]) - vals[voff[nz]]
    gsize[last] = nb - s
    mask = np.ones(len(gsize), bool)
    mask[last] = False
    gsize[mask] = vals[rest]
    if (gsize < 0).any():
        raise ValueError("negative implicit last-group size")
    gstart = np.concatenate([[0], np.cumsum(gsize, dtype=np.int64)[:-1]])
    return gsize, grec, gstart


class PosIndex:
    """Position -> bit indices (sorted)."""

    def __init__(self, pos):
        self.order = np.argsort(pos, kind="stable")
        self.sp = np.asarray(pos)[self.order]

    def bits(self, P):
        i, j = np.searchsorted(self.sp, P), np.searchsorted(self.sp, P, "right")
        return self.order[i:j]


def stats(die):
    a = load(die)
    n, nb, vals, voff, tr, flag, pos = a["n"], a["nb"], a["vals"], a["voff"], a["lead"], a["flag"], a["pos"]
    print(f"{die}: records {len(n)}, empty (n=0) {(n == 0).sum()}, nb=0 {(nb == 0).sum()}, bits {len(pos)}")
    shapes = collections.Counter(zip(n.tolist(), nb.tolist()))
    print("  shapes (n, nb):", shapes.most_common(12))
    nz = n > 0
    v0 = vals[voff[nz]]
    print("  vals[0]:", collections.Counter(v0.tolist()).most_common(8))
    rest = np.ones(len(vals), bool)
    rest[voff[nz]] = False
    print("  vals[1:]:", collections.Counter(vals[rest].tolist()).most_common(12))
    print("  flag:", collections.Counter(flag.tolist()).most_common(12))
    print("  lead:", collections.Counter(tr.tolist()).most_common(12))
    print(f"  running sum range {pos.min()}..{pos.max()}; M = {FRAMES[die]} x {FRAME_BITS[die]} = {FRAMES[die] * FRAME_BITS[die]}")
    # first group = 3 bits?  check sum(vals[1:]) + first vs nb
    s = np.add.reduceat(vals.astype(np.int64), voff[nz]) - v0 if nz.any() else 0
    d = nb[nz] - s
    print("  nb - sum(vals[1:]):", collections.Counter(d.tolist()).most_common(8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("parse", "stats"))
    ap.add_argument("--die", default="stingray4")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_ddb_asm.log"))])
    if a.cmd == "parse":
        parse(a.die)
    elif a.cmd == "stats":
        stats(a.die)


if __name__ == "__main__":
    main()
