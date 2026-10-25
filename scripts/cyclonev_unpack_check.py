#!/usr/bin/env python3.15t
"""Re-run cyclonev_unpack.py over every corpus bitstream.rbf; the .bt must equal the stored decomp.bt.

  python3.15t scripts/cyclonev_unpack_check.py [--corpus DIR] [--workers 8]
Log: tmp/logs/cyclonev_unpack_check.log; outputs: tmp/unpack_check/<design>.bt
"""
import argparse
import concurrent.futures as cf
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "tmp", "unpack_check")
# one unpack = ~3 s (mistral decomp 2.7 s measured); limit covers 30 s per design; expiry = FAIL
LIMIT_S = 30


def one(corpus, name):
    rbf = os.path.join(corpus, name, "bitstream.rbf")
    ref = os.path.join(corpus, name, "decomp.bt")
    bt = os.path.join(OUT, name + ".bt")
    if os.path.exists(bt):
        os.remove(bt)
    try:
        r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "cyclonev_unpack.py"),
                            rbf, bt, "--rbf", os.path.join(OUT, name + ".rbf")],
                           capture_output=True, text=True, timeout=LIMIT_S)
    except subprocess.TimeoutExpired:
        return name, f"timeout {LIMIT_S}s"
    if r.returncode:
        return name, "unpack failed: " + (r.stderr or r.stdout)[-300:]
    same = open(bt, "rb").read() == open(ref, "rb").read()
    return name, None if same else "bt differs from decomp.bt"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=os.path.join(REPO, "corpus", "cyclonev"))
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    names = sorted(n for n in os.listdir(a.corpus)
                   if os.path.isfile(os.path.join(a.corpus, n, "bitstream.rbf"))
                   and os.path.isfile(os.path.join(a.corpus, n, "decomp.bt")))
    bad = []
    with cf.ThreadPoolExecutor(a.workers) as ex, \
            open(os.path.join(REPO, "tmp", "logs", "cyclonev_unpack_check.log"), "w") as log:
        for name, err in ex.map(lambda n: one(a.corpus, n), names):
            print(name, err or "OK", file=log, flush=True)
            if err:
                bad.append((name, err))
    print(f"{len(names) - len(bad)}/{len(names)} identical to decomp.bt")
    for n, e in bad[:20]:
        print("FAIL", n, e)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
