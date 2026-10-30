#!/usr/bin/env python3
"""Single-bit flips of sof tag 18 (option register): which rbf header bytes change (#165, #169).

  python3.15t scripts/cycloneiv_clean_option_header_flip.py [bit ...]   # default 7 38 94 71 106 112 130; log tmp/logs/option_header_flip.log

- Settles whether a bit with a header cell in the CRC bytes (header bytes 41, 42) is stored or only follows the header CRC.
- Flips the value half (bit i) of the vendor sfl sof, quartus_cpf, compares all header bytes (40 header bytes = bit 0..39 of each lane, then 2 CRC bytes = bit 40, 41) with the unflipped rbf.
"""
import gzip
import logging
import os
import sys

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import sofio as S  # noqa: E402
import cycloneiv_clean_cff_tables as T  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "option_header_flip.log")
WORK = os.path.join(REPO, "tmp", "option_header_flip")
DEFAULT = (7, 38, 94, 71, 106, 112, 130)


def hdr(rbf):
    d = open(rbf, "rb").read(120)
    s = d.index(0x6A)
    return d[s + 1:s + 43]


def lane_bits(a, b):
    return [(f"lane{k}", f"bit{j}") for j in range(42) for k in range(8) if (a[j] ^ b[j]) >> k & 1]


def main():
    bits = [int(x) for x in sys.argv[1:]] or list(DEFAULT)
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = logging.getLogger("ohf")
    log.setLevel(logging.INFO)
    log.addHandler(logging.FileHandler(LOG, "w"))
    log.addHandler(logging.StreamHandler(sys.stdout))
    src = S.programmer_sof(T.SRC)
    d0 = gzip.decompress(open(src, "rb").read())
    off, ln = T.sections(d0)[18]
    base = np.unpackbits(np.frombuffer(d0[off:off + ln], np.uint8), bitorder="little")
    ref = os.path.join(WORK, "ref")
    T.make_sof(src, ref + ".sof", 18, base, 0)
    S.to_rbf(ref + ".sof", ref + ".rbf")
    h0 = hdr(ref + ".rbf")
    for i in bits:
        b = base.copy()
        b[i] ^= 1
        p = os.path.join(WORK, f"b{i}")
        T.make_sof(src, p + ".sof", 18, b, 0)
        S.to_rbf(p + ".sof", p + ".rbf")
        h = hdr(p + ".rbf")
        ch = lane_bits(h0, h)
        log.info("value bit %3d (was %d): header bits changed %s; CRC-only %s", i, base[i], ch, all(int(x[3:]) >= 40 for _, x in ch) if ch else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
