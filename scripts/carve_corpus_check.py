#!/usr/bin/env python3.15t
"""Run the carver over the whole existing 228-bitstream corpus.

Every file there IS a bare ECP5 bitstream, so the carver must find exactly one
in each and reproduce it byte-identically. Any miss is a carver blind spot;
any extra hit is a false positive. This is the strongest available check that
the carver will not silently mangle a vendor blob.

Gzip'd (Diamond) files are expected to be found only after unwrapping.
"""
import hashlib
import json
import os
import subprocess
import sys

REPO = "/mnt/2tb/git/pluribus"
PY = "/home/dan/opt/cpython-315t/bin/python3.15t"
CORPUS = os.path.join(REPO, "corpus", "ecp5")
WORK = os.path.join(REPO, "tmp", "carve-corpus-check")


def main():
    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(WORK, "out")
    os.makedirs(out, exist_ok=True)
    js = os.path.join(WORK, "recs.json")

    files = sorted(os.path.join(CORPUS, f) for f in os.listdir(CORPUS)
                   if f.endswith(".bit"))
    print(f"corpus: {len(files)} bitstreams")

    cmd = [PY, os.path.join(REPO, "scripts", "ecp5_carve.py"),
           *files, "--out", out, "--json", js]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print("carve failed:", p.returncode)
        print(p.stderr[-4000:])
        sys.exit(1)
    recs = json.load(open(js))

    by_src = {}
    for r in recs:
        by_src.setdefault(os.path.basename(r["source_file"]), []).append(r)

    misses, multis, exact, inexact = [], [], 0, []
    for f in files:
        b = os.path.basename(f)
        hits = by_src.get(b, [])
        if not hits:
            misses.append(b)
            continue
        if len(hits) > 1:
            multis.append((b, len(hits)))
        orig = open(f, "rb").read()
        gz = orig[:2] == b"\x1f\x8b"
        osha = hashlib.sha256(orig).hexdigest()
        if any(h["sha256"] == osha for h in hits):
            exact += 1
        else:
            inexact.append((b, gz, [(h["bytes"], len(orig)) for h in hits]))

    print(f"\nfound in       : {len(by_src)}/{len(files)}")
    print(f"byte-identical : {exact}/{len(files)}")
    print(f"misses         : {len(misses)}")
    for m in misses[:15]:
        print("   MISS", m)
    print(f"multi-hit      : {len(multis)}")
    for m in multis[:15]:
        print("   MULTI", m)
    print(f"inexact        : {len(inexact)}")
    for b, gz, szs in inexact[:15]:
        print(f"   INEXACT gzip={gz} {b} carved/orig={szs}")

    devs = {}
    for r in recs:
        devs[r["device"]] = devs.get(r["device"], 0) + 1
    print("\ndevices:", dict(sorted(devs.items())))


if __name__ == "__main__":
    main()
