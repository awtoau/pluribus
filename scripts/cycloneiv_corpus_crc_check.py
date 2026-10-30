#!/usr/bin/env python3.15t
"""Frame-CRC integrity check of every corpus bitstream.rbf (EP4CGX150).

  python3.15t scripts/cycloneiv_corpus_crc_check.py [--root corpus/cycloneiv] [--workers 8]
Per file: header CRC, then CRC-16 of each 796-byte frame (CRAM frames after the 37 periphery frames) vs its trailing 2 bytes.
Log: tmp/logs/cycloneiv_corpus_crc_check.log; failures: tmp/cycloneiv_corpus_crc_bad.json.
Stall guard: no file result for 60 s = hung (expected ~0.1 s per file); expiry logs the last design.
"""
import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cycloneiv_decompress as cd  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_corpus_crc_check.log")
BAD = os.path.join(REPO, "tmp", "cycloneiv_corpus_crc_bad.json")
FRAME = 796                 # source: docs/cycloneiv-bitstream.md EP4CGX150 frame bytes (pad + 793 data + 2 CRC)
PERIPHERY = 37              # source: docs/cycloneiv-bitstream.md periphery frames before the CRAM
CRAM_FRAMES = 6154          # source: docs/cycloneiv-bitstream.md EP4CGX150 CRAM frames
STALL_S = 60


def check(path):
    d = open(path, "rb").read()
    s = cd.PREAMBLE
    ok = cd.frames_ok_np(d, s + PERIPHERY * FRAME, FRAME)
    return {"size": len(d), "header_crc_ok": bool(cd.hdr_crc_ok(d, s)), "cram_frames_ok": int(ok[:CRAM_FRAMES].sum()),
            "cram_frames_walked": int(min(len(ok), CRAM_FRAMES)), "frames_after": int(len(ok) - CRAM_FRAMES)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(REPO, "corpus", "cycloneiv"))
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
    files = [(d, os.path.join(a.root, d, "bitstream.rbf")) for d in sorted(os.listdir(a.root))]
    files = [(d, p) for d, p in files if os.path.exists(p)]
    logging.info("%d bitstreams under %s", len(files), a.root)
    bad, n_ok, t0, last = {}, 0, time.time(), time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(check, p): d for d, p in files}
        for f in as_completed(futs):
            d = futs[f]
            r = f.result()
            last = time.time()
            if r["header_crc_ok"] and r["cram_frames_ok"] == CRAM_FRAMES and r["cram_frames_walked"] == CRAM_FRAMES:
                n_ok += 1
            else:
                bad[d] = r
            if (n_ok + len(bad)) % 2000 == 0:
                logging.info("%d checked, %d bad, %.0fs", n_ok + len(bad), len(bad), time.time() - t0)
            if last - t0 > 0 and time.time() - last > STALL_S:
                logging.error("stall: last design %s", d)
    json.dump(bad, open(BAD, "w"), indent=1)
    logging.info("DONE: %d ok, %d bad of %d (%.0fs)", n_ok, len(bad), len(files), time.time() - t0)


if __name__ == "__main__":
    main()
