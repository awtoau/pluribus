#!/usr/bin/env python3.15t
"""Cyclone V unpack stage: flash image / .rbf -> Mistral `.bt` decompile.

Steps (log: tmp/logs/cyclonev_unpack.log):
  - strip leading/trailing 0xFF flash padding -> plain .rbf (skipped if the input has none)
  - mistral-cv decomp <device> <rbf> <bt>   (the `.bt` is what the cyclonev lifter reads)
Refuses to overwrite an existing output (same contract as trellis_unpack.py).

  python3.15t scripts/cyclonev_unpack.py IN.bin OUT.bt [--device 5CEBA4U19C8] [--rbf KEEP.rbf]
"""
import argparse
import logging
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import toolchain  # noqa: E402
from db import die  # noqa: E402

# mistral-cv decomp of a 2 MB rbf: 2.7 s wall measured 2026-10-24; limit ~5x (cold cache).
# Expiry: subprocess killed, die() names the limit.
DECOMP_LIMIT_S = 15


def strip_ff(raw: bytes) -> bytes:
    a = len(raw) - len(raw.lstrip(b"\xff"))
    b = len(raw.rstrip(b"\xff"))
    return raw[a:b]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bin")
    ap.add_argument("bt")
    ap.add_argument("--device", default="5CEBA4U19C8")
    ap.add_argument("--rbf", help="where to keep the stripped .rbf (default: <bt>.rbf)")
    a = ap.parse_args()

    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_unpack.log"))])
    log = logging.getLogger("cyclonev_unpack")

    if os.path.exists(a.bt):
        die(f"refusing to overwrite {a.bt}")
    rbf = a.rbf or a.bt + ".rbf"
    raw = open(a.bin, "rb").read()
    body = strip_ff(raw)
    log.info("%s: %d bytes -> %d after 0xFF strip; first bytes %s", a.bin, len(raw),
             len(body), body[:8].hex())
    if not body:
        die("empty image after stripping 0xFF")
    os.makedirs(os.path.dirname(os.path.abspath(rbf)), exist_ok=True)
    open(rbf, "wb").write(body)
    os.makedirs(os.path.dirname(os.path.abspath(a.bt)), exist_ok=True)
    try:
        r = subprocess.run([toolchain.mistral_cv(), "decomp", a.device, rbf, a.bt],
                           capture_output=True, text=True, timeout=DECOMP_LIMIT_S)
    except subprocess.TimeoutExpired:
        die(f"mistral-cv decomp exceeded {DECOMP_LIMIT_S}s")
    log.info("mistral-cv rc=%d\n%s%s", r.returncode, r.stdout[-1500:], r.stderr[-1500:])
    if r.returncode != 0:
        die(f"mistral-cv decomp failed rc={r.returncode}")
    log.info("wrote %s (%d bytes)", a.bt, os.path.getsize(a.bt))


if __name__ == "__main__":
    main()
