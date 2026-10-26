#!/usr/bin/env python3
"""Synthetic control for lift_realism.py: a Cyclone V .rbf whose CRAM is random bytes.

Container (sync, option RAM, PRAM) is copied from a real Quartus .rbf so the decoder accepts it.
  frames  : base = UNCOMPRESSED .rbf.  Every CRAM frame body = random bytes (first/last frame
            keep their 843e01 / 429f00 markers), per-frame CRC16 recomputed -> passes every check.
  coded   : base = COMPRESSED .rbf.  The nibble-coded CRAM region = --coded-len random bytes.
            Same decode path as an opaque compressed image; the decoder refuses it
            (frame marker / CRC) unless cyclonev_unpack.py --allow-invalid is used.
Seeded (numpy default_rng).  Output goes to ./tmp/, never committed.

  python3 scripts/cyclonev_random_control.py frames BASE.rbf OUT.rbf [--seed N]
  python3 scripts/cyclonev_random_control.py coded BASE.compressed.rbf OUT.rbf --coded-len N [--seed N]
"""
import argparse
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_decompress as cd  # noqa: E402

log = logging.getLogger("cyclonev_random_control")


def frames_control(base: bytes, rng) -> bytes:
    info = {}
    cd.decompress(base, info)
    if info.get("compressed") and not info.get("note"):
        raise SystemExit("frames mode needs an uncompressed base .rbf")
    start, g, n = info["cram_start"], info["cram_frame"], info["cram_frames"]
    out = bytearray(base)
    for i in range(n):
        q = start + i * g
        body = bytearray(rng.bytes(g - 2))
        if i == 0:
            body[:3] = cd.FIRST_CRAM
        if i == n - 1:
            body[:3] = cd.LAST_CRAM
        c = cd.crc16(bytes(body))
        out[q:q + g] = bytes(body) + bytes([c & 0xFF, c >> 8])
    log.info("random CRAM: %d frames x %d B from byte %d", n, g, start)
    return bytes(out)


def coded_control(base: bytes, rng, coded_len: int) -> bytes:
    s, sh = cd.find_sync(base)
    if sh:
        base = cd.realign(base, sh)
    h = cd.parse_header(base)
    if not h["compressed"]:
        raise SystemExit("coded mode needs a compressed base .rbf")
    log.info("random coded CRAM: %d B after byte %d", coded_len, h["cram_start"])
    return base[:h["cram_start"]] + rng.bytes(coded_len)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=("frames", "coded"))
    ap.add_argument("base")
    ap.add_argument("out")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--coded-len", type=int, help="coded mode: random bytes after the PRAM")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_random_control.log"))])
    rng = np.random.default_rng(a.seed)
    base = open(a.base, "rb").read()
    if a.mode == "frames":
        out = frames_control(base, rng)
    else:
        if not a.coded_len:
            raise SystemExit("--coded-len required")
        out = coded_control(base, rng, a.coded_len)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "wb").write(out)
    log.info("wrote %s (%d bytes, seed %d)", a.out, len(out), a.seed)


if __name__ == "__main__":
    main()
