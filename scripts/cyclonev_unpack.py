#!/usr/bin/env python3.15t
"""Cyclone V unpack stage: flash image / .rbf -> Mistral `.bt` decompile.

Steps (log: tmp/logs/cyclonev_unpack.log):
  - locate the `jjjj` sync (bit-shifted `a6a6a6a6` form realigned); keep the 0x80-byte 0xFF
    preamble + sync (Mistral reads the option RAM at absolute 0x84), drop only padding before it
  - validate via cyclonev_decompress: sync, option-RAM CRC16, PRAM/CRAM frame CRC16s, postamble;
    die() naming the failing check (no garbage to the lifter).  Compressed input is expanded.
  - mistral-cv decomp <device> <rbf> <bt>   (the `.bt` is what the cyclonev lifter reads)
Refuses to overwrite an existing output (same contract as trellis_unpack.py).
Decision: #114.

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
import cyclonev_decompress as cd  # noqa: E402
import toolchain  # noqa: E402
from db import die  # noqa: E402

# mistral-cv decomp of a 2 MB rbf: 2.7 s wall measured 2026-10-24; limit ~5x (cold cache).
# Expiry: subprocess killed, die() names the limit.
DECOMP_LIMIT_S = 15


PREAMBLE = 0x80  # 0xFF bytes before the sync in every quartus_cpf .rbf (sync at 0x80, option RAM 0x84)


def normalise(raw: bytes) -> bytes:
    """Validated, uncompressed .rbf starting at the preamble.  die() on any failed check."""
    try:
        n, sh = cd.find_sync(raw)
        if sh:
            raw = cd.realign(raw, sh)
        if n < PREAMBLE:
            die(f"preamble too short: sync at byte {n}, need {PREAMBLE:#x} 0xFF bytes before it "
                "(stripped leading 0xFF? Mistral would misread the option RAM, #114)")
        return cd.decompress(raw[n - PREAMBLE:])
    except cd.FormatError as e:
        die(f"not a valid Cyclone V .rbf: {e}")


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
    body = normalise(raw)
    log.info("%s: %d bytes -> %d validated (preamble kept); first bytes %s", a.bin, len(raw),
             len(body), body[:4].hex())
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
