#!/usr/bin/env python3.15t
"""asm.ddb record/group/block tables for Cyclone IV GX (docs/altera/cycloneIV/cycloneiv-ddb-format.md).  No coordinate model.

Record = routing wire (vendor name, icname.ddb); group = destination mux; entry = (address, b0, b1).
Raw addresses only: asm address -> plane cell is the clean address engine's job (docs/altera/cycloneIV/cycloneiv-clean-pipeline.md, A3-A5).

  python3.15t scripts/cycloneiv_asm_prep.py prepare     # -> tmp/ddb/<die>_dec_*.npy + _dec_names.pkl
Log tmp/logs/cycloneiv_asm_prep.log.
"""
import logging
import os
import pickle
import struct
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_ddb_asm as A  # noqa: E402
import fastops  # noqa: E402

log = logging.getLogger("cycloneiv_asm_prep")
DIE = "stingray4"
DEC = os.path.join(A.TMP, f"{DIE}_dec")


def db_die(msg):
    log.error(msg)
    raise SystemExit(msg)


def icnames(die=DIE):
    """record id -> vendor name (first icname table; ids start at the header's base id, deltas of 1)."""
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


def programmed(b0, b1, first=None):
    """Which entries of a group are programmed 1: the select bit (the group's first entry; b0 = +1, or 0 on
    ~3 % of the 3-groups), and a second-level bit iff b1 == -1."""
    p = (np.asarray(b0) == 1) | (np.asarray(b1) == -1)
    if first is not None:
        p = p | np.asarray(first)
    return p


def prepare():
    a = A.load(DIE)
    pos, flag = np.asarray(a["pos"]).astype(np.int64), np.asarray(a["flag"])
    gsize, grec, gstart = A.group_sizes(a)
    gid = np.repeat(np.arange(len(gsize), dtype=np.int32), gsize)
    b0 = (flag & 0xFF).astype(np.int8)
    b1 = ((flag >> 8) & 0xFF).astype(np.int8)
    names = icnames()
    first = np.zeros(len(pos), bool)
    first[gstart[gsize == 3]] = True          # the select entry of every 3-group (b0 = 0 on some)
    pred = programmed(b0, b1, first)
    # block key: the (up to 2) non-select entry addresses of the group; groups sharing them form one mux
    isA = b0 != 1
    key = np.full((len(gsize), 2), -1, np.int64)
    order = np.lexsort((pos, gid))
    gid_o, pos_o, isA_o = gid[order], pos[order], isA[order]
    g_a, l_a = gid_o[isA_o], pos_o[isA_o]
    head = np.concatenate([[True], g_a[1:] != g_a[:-1]])
    key[g_a[head], 0] = l_a[head]
    idx_first = np.flatnonzero(head)
    second = idx_first + 1
    ok = second < len(g_a)
    ok[ok] &= g_a[second[ok]] == g_a[idx_first[ok]]
    key[g_a[second[ok]], 1] = l_a[second[ok]]
    noA = key[:, 0] < 0           # groups without non-select entries: key on their own first address
    key[noA, 0] = pos[gstart[noA]]
    _, block = fastops.unique_rows2_inverse(key)
    block = block.astype(np.int32)
    u, inv = fastops.unique_inverse(block[gid].astype(np.int64) << 40 | pos)
    e_ukey, ukey_block = inv.astype(np.int32), (u >> 40).astype(np.int32)
    os.makedirs(A.TMP, exist_ok=True)
    for name, arr in (("pred", pred), ("gid", gid), ("grec", grec), ("gstart", gstart), ("gsize", gsize),
                      ("block", block), ("b0", b0), ("e_ukey", e_ukey), ("ukey_block", ukey_block)):
        np.save(f"{DEC}_{name}.npy", arr)
    pickle.dump(names, open(f"{DEC}_names.pkl", "wb"))
    log.info("prepared: %d entries, %d groups, %d blocks, %d named records", len(pos), len(gsize), block.max() + 1, len(names))


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_asm_prep.log")),
                                  logging.StreamHandler()])
    if sys.argv[1:] != ["prepare"]:
        raise SystemExit(__doc__)
    prepare()


if __name__ == "__main__":
    main()
