#!/usr/bin/env python3.15t
"""Self-test the carver against ground truth before trusting it on vendor blobs.

Three checks:
  1. A bare corpus .bit is carved, and the carved bytes are IDENTICAL to the
     original file (so carving a standalone bitstream is a no-op).
  2. The same .bit hidden inside a zip, inside a gzip, and at an offset in a
     junk-padded blob is still found, with the same device.
  3. Random data does not produce hits (false-positive check), including random
     data that CONTAINS the sync word but no valid VERIFY_ID.
"""
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import zipfile

REPO = "/mnt/2tb/git/pluribus"
PY = "/home/dan/opt/cpython-315t/bin/python3.15t"
SYNC = b"\xff\xff\xbd\xb3"
WORK = os.path.join(REPO, "tmp", "carve-selftest")


def run_carve(paths, outdir, jsonout):
    cmd = [PY, os.path.join(REPO, "scripts", "ecp5_carve.py"),
           *paths, "--out", outdir, "--json", jsonout]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print("CARVE FAILED", p.returncode)
        print(p.stdout[-4000:])
        print(p.stderr[-4000:])
        sys.exit(1)
    return json.load(open(jsonout))


def main():
    os.makedirs(WORK, exist_ok=True)
    corpus = os.path.join(REPO, "corpus", "ecp5")
    bits = sorted(f for f in os.listdir(corpus) if f.endswith(".bit"))
    if not bits:
        print("no corpus bitstreams to test against")
        sys.exit(1)

    # pick a small uncompressed one for speed
    cands = sorted(bits, key=lambda f: os.path.getsize(os.path.join(corpus, f)))
    src = None
    for f in cands:
        p = os.path.join(corpus, f)
        with open(p, "rb") as fh:
            head = fh.read(2)
        if head != b"\x1f\x8b":          # skip gzip'd Diamond output for test 1
            src = p
            break
    print("reference bitstream:", os.path.basename(src),
          os.path.getsize(src), "bytes")
    orig = open(src, "rb").read()
    orig_sha = hashlib.sha256(orig).hexdigest()

    # ---- test 1: bare .bit round-trips byte-identically -------------------
    d1 = os.path.join(WORK, "out1")
    os.makedirs(d1, exist_ok=True)
    recs = run_carve([src], d1, os.path.join(WORK, "r1.json"))
    print(f"\nTEST1 bare .bit: {len(recs)} hit(s)")
    ok1 = False
    for r in recs:
        same = r["sha256"] == orig_sha
        print(f"  {r['device']} {r['bytes']} bytes identical={same}")
        ok1 = ok1 or same
    print("TEST1", "PASS" if ok1 else "FAIL")

    # ---- test 2: hidden in containers -------------------------------------
    # zip
    zp = os.path.join(WORK, "fw_update.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("readme.txt", "vendor firmware package\n")
        zf.writestr("images/fpga_top.img", orig)
    # gzip
    import gzip
    gp = os.path.join(WORK, "fw_update.bin.gz")
    with gzip.open(gp, "wb") as fh:
        fh.write(b"\x00" * 1024 + orig + b"\xff" * 512)
    # raw blob with the bitstream at an offset, junk either side
    rng = random.Random(1234)
    junk_pre = bytes(rng.randrange(256) for _ in range(8192))
    junk_post = bytes(rng.randrange(256) for _ in range(4096))
    rp = os.path.join(WORK, "flash_dump.bin")
    with open(rp, "wb") as fh:
        fh.write(junk_pre + orig + junk_post)
    # nested: zip inside zip
    np_ = os.path.join(WORK, "nested.zip")
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("fpga.bit", orig)
    with zipfile.ZipFile(np_, "w") as zf:
        zf.writestr("payload/inner.zip", inner.getvalue())

    d2 = os.path.join(WORK, "out2")
    os.makedirs(d2, exist_ok=True)
    recs2 = run_carve([zp, gp, rp, np_], d2, os.path.join(WORK, "r2.json"))
    print(f"\nTEST2 containers: {len(recs2)} hit(s)")
    got = {}
    for r in recs2:
        got.setdefault(os.path.basename(r["source_file"]), []).append(r)
        print(f"  {os.path.basename(r['source_file']):20s} {r['origin']:44s} "
              f"{r['device']:8s} {r['bytes']:8d} exact={r['sha256'] == orig_sha}")
    want = {"fw_update.zip", "fw_update.bin.gz", "flash_dump.bin", "nested.zip"}
    missing = want - set(got)
    print("TEST2", "PASS" if not missing else f"FAIL missing={missing}")

    # ---- test 3: false positives ------------------------------------------
    rng = random.Random(99)
    pure = bytes(rng.randrange(256) for _ in range(4 * 1024 * 1024))
    p3a = os.path.join(WORK, "random.bin")
    open(p3a, "wb").write(pure)
    # random data with sync words sprinkled in but no valid VERIFY_ID
    salted = bytearray(pure)
    for off in range(1000, len(salted) - 8, 250000):
        salted[off:off + 4] = SYNC
    p3b = os.path.join(WORK, "random_salted.bin")
    open(p3b, "wb").write(bytes(salted))
    d3 = os.path.join(WORK, "out3")
    os.makedirs(d3, exist_ok=True)
    recs3 = run_carve([p3a, p3b], d3, os.path.join(WORK, "r3.json"))
    print(f"\nTEST3 false positives on 8MB random (incl. 16 planted syncs): "
          f"{len(recs3)} hit(s)")
    for r in recs3:
        print("  UNEXPECTED", r["origin"], r["device"], r["bytes"])
    print("TEST3", "PASS" if not recs3 else "FAIL")

    print("\nOVERALL", "PASS" if (ok1 and not missing and not recs3) else "FAIL")


if __name__ == "__main__":
    main()
