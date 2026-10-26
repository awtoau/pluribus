#!/usr/bin/env python3.15t
"""Cyclone IV GX `routing.ddb`: the node table (decoded) and the regions after it (not decoded).

Format: docs/cycloneiv-ddb-format.md "routing.ddb".  Body `u32 4, cols, rows, N`, then N x (i16 dx, i16 dy,
i32 c, i32 dn): cumsum(dx, dy) = the node's tile (vendor x = 115 - fitter X on EP4CGX150, y = fitter Y),
cumsum(dn) = offset of its fan-out list (2 ints per fan-out, lists shared between nodes), node id = asm record id.

  python3.15t scripts/cycloneiv_ddb_routing.py nodes [--die stingray4]   # -> tmp/ddb/<die>_rt_nodes.npy + summary
Streams the body; peak RSS ~0.4 GB.  Log tmp/logs/cycloneiv_ddb_routing.log.
"""
import argparse
import collections
import logging
import os
import struct
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_ddb_decode as dd  # noqa: E402
import cycloneiv_ddb_asm as A  # noqa: E402

log = logging.getLogger("cycloneiv_ddb_routing")
NODE = np.dtype([("dx", "<i2"), ("dy", "<i2"), ("c", "<i4"), ("dn", "<i4")])


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("nodes",))
    ap.add_argument("--die", default="stingray4")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_ddb_routing.log"))])
    nodes(a.die)


if __name__ == "__main__":
    main()
