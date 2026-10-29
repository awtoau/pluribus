#!/usr/bin/env python3.15t
"""A/B verification of the Python perf pass (#145, docs/perf-pass.md): new path vs reference, bit-identical.

  python3.15t scripts/perf_pass_verify.py decode [--corpus N] # decompress() / plane keys vs tests/ref_decode.py
Log tmp/logs/perf_pass_verify.log; results tmp/perf_pass_verify_<cmd>.json.  Any difference exits 1.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
log = logging.getLogger("perf_pass_verify")
SRC = REPO / "sources" / "cycloneiv-corpus"
CORPUS = REPO / "corpus" / "cycloneiv"


def setup(cmd):
    os.makedirs(REPO / "tmp" / "logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "perf_pass_verify.log"),
                                  logging.StreamHandler()])


def cgx150_images(n_rb):
    out = [(p.parent.name + "/" + p.name, p) for p in sorted(SRC.glob("poseidon_*/*.rbf"))]
    out += [("neptuno_cgx150_mc2/mc2.rbf", SRC / "neptuno_cgx150_mc2" / "mc2.rbf")]
    out += [(f"gx150_rb_{i:03d}", CORPUS / f"gx150_rb_{i:03d}" / "bitstream.rbf") for i in range(0, 150, max(1, 150 // max(n_rb, 1)))][:n_rb]
    return out


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("decode"); p.add_argument("--corpus", type=int, default=200)
    a = ap.parse_args()
    setup(a.cmd)
    import perf_pass_decode
    bad = perf_pass_decode.run(a, log)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
