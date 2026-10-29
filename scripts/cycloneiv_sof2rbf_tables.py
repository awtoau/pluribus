#!/usr/bin/env python3.15t
"""Derive the sof -> rbf table of EP4CGX150 (A5): mirrored 256-frame blocks and the cell mask.  Black box: quartus_cpf only.

Method: 26 bit-plane sofs (sof data bit i = bit p of i) from the vendor sfl sof, converted by quartus_cpf; the 26 rbf CRAM
planes give every rbf cell its sof index.  Checks: bijection, v closed form, frame 6153 - s outside the mirrored blocks.
Output: databases/cycloneiv/sof2rbf_mask.npz (local, not committed).  Log: tmp/logs/cycloneiv_sof2rbf_tables.log
usage: python3.15t scripts/cycloneiv_sof2rbf_tables.py
"""
import logging
import os
import shutil
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from lifters.cycloneiv_clean import plane as P  # noqa: E402
from lifters.cycloneiv_clean import sofio as S  # noqa: E402

log = logging.getLogger("sof2rbf_tables")
SRC = "sfl_ep4cgx150.sof"
WORK = os.path.join(REPO, "tmp", "sof2rbf_tables")
PLANES = 26                # 2^26 > N_BITS


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_sof2rbf_tables.log"), mode="w")])
    src = S.programmer_sof(SRC)
    os.makedirs(WORK, exist_ok=True)
    i = np.arange(P.N_BITS, dtype=np.int64)
    idx = np.zeros((P.FRAMES, P.ROWS, 8), np.int32)
    for p in range(PLANES):
        sof, rbf = os.path.join(WORK, f"plane{p}.sof"), os.path.join(WORK, f"plane{p}.rbf")
        S.make_sof(src, sof, ((i >> p) & 1).astype(np.uint8))
        S.to_rbf(sof, rbf)
        idx |= S.rbf_cram(rbf).astype(np.int32) << p
        os.remove(sof)
        os.remove(rbf)
        log.info("plane %d done", p)
    np.save(os.path.join(WORK, "idx.npy"), idx)      # kept until the checks pass (debug aid); removed with WORK
    if int(idx.max()) >= P.N_BITS:
        raise SystemExit(f"cell with sof index {int(idx.max())} >= N_BITS")
    if len(np.unique(idx)) != P.N_BITS:
        raise SystemExit("rbf cells are not a bijection onto the sof bits")
    s, v = idx % P.FRAMES, idx // P.FRAMES
    j = np.arange(1, P.ROWS + 1)[None, :, None]
    k = np.arange(8)[None, None, :]
    if not (v == P.ROWS * k + P.ROWS - j).all():
        raise SystemExit("v closed form fails")
    r = np.arange(P.FRAMES)[:, None, None]
    dev = s != P.FRAMES - 1 - r                              # cells off the default frame reversal
    rows = np.flatnonzero(dev.any(axis=(1, 2)))
    starts = [int(a) for a in rows if a - 1 not in set(rows.tolist())]
    blocks = []
    for a in starts:
        run = rows[(rows >= a) & (rows < a + 256)]
        if len(run) != 256 or run[0] != a or run[-1] != a + 255:
            raise SystemExit(f"deviating frames at {a} are not a 256-frame block")
        blocks.append(a)
    if sum(len(rows[(rows >= a) & (rows < a + 256)]) for a in blocks) != len(rows):
        raise SystemExit("deviating frames outside the blocks")
    mask = dev[blocks[0]].copy()                             # [ROWS, 8]
    for b in blocks:
        mirrored = s[b:b + 256] == (P.FRAMES - 1 - b - 255) + (r[b:b + 256] - b)
        if not (dev[b:b + 256] == mask[None]).all() or not (mirrored == mask[None]).all():
            raise SystemExit(f"block {b}: cells are not mask-mirrored")
    log.info("blocks %s; mirrored cells per frame %d of %d", blocks, int(mask.sum()), mask.size)
    out = os.path.join(REPO, "databases", "cycloneiv")
    os.makedirs(out, exist_ok=True)
    np.savez(os.path.join(out, "sof2rbf_mask.npz"), blocks=np.array(blocks, np.int32), mask=mask,
             source=np.array(SRC), source_sha256=np.array(S.sha256(src)))
    shutil.rmtree(WORK, ignore_errors=True)
    log.info("wrote %s/sof2rbf_mask.npz", out)


if __name__ == "__main__":
    main()
