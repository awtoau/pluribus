#!/usr/bin/env python3.15t
"""Cyclone IV null-control audit (#165): recompute the diffs of the on-disk null builds from the rbfs.
Nulls are compared against the ORIGINAL base/spec of the batch's first arc (null_*_b vs orig _b, null_*_s vs orig _s), NOT b vs s of the
nulls (b vs s differs by design: the spec forces a route). Prints region of each differing cell (plane frame/v, raw rbf bytes) .
Args: A:B ... (explicit pairs) or ORIG_B ORIG_S NULL_PREFIX  (e.g. gxr4df_b_42_24_4__46_24_6 gxr4df_s_i0_X42Y24_from42_24_5 gxr4df_null)
Log tmp/logs/cycloneiv_null_audit.log.
"""
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_corpus as cc  # noqa: E402

log = logging.getLogger("nullaudit")
CORPUS = cc.CORPUS


def rbf(n):
    return np.frombuffer((CORPUS / n / "bitstream.rbf").read_bytes(), np.uint8)


def cells(n):
    return set(cc.load_plane_only(n).keys.tolist())


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_null_audit.log"), mode="w")])
    PVMAX = 6368
    if all(":" in x for x in sys.argv[1:]):
        pairs = [tuple(x.split(":")) for x in sys.argv[1:]]          # explicit A:B pairs
    else:
        ob, os_, pfx = sys.argv[1:4]
        pairs = [(f"{pfx}_{k}_{r}", ref) for k in ("rename", "seed") for r, ref in (("b", ob), ("s", os_))]
        pairs += [(f"{pfx}_rename_b", f"{pfx}_seed_b"), (f"{pfx}_rename_s", f"{pfx}_seed_s"), (ob, os_), (f"{pfx}_rename_b", f"{pfx}_rename_s")]
    for a, b in pairs:
        ra, rb = rbf(a), rbf(b)
        n = min(len(ra), len(rb))
        bd = np.flatnonzero(ra[:n] != rb[:n])
        ca, cb = cells(a), cells(b)
        d = sorted(ca ^ cb)
        log.info("%s vs %s: rbf size %d/%d, differing bytes %d, plane diff cells %d", a, b, len(ra), len(rb), len(bd), len(d))
        if len(bd) and len(bd) <= 40:
            log.info("  byte offsets %s (frame %s)", bd.tolist(), sorted({(int(x) - 32) // 796 for x in bd.tolist()}))
        if d and len(d) <= 40:
            log.info("  cells (frame, v): %s", [(x // PVMAX, x % PVMAX) for x in d])


if __name__ == "__main__":
    main()
