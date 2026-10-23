#!/usr/bin/env python3
"""Check scripts/cyclonev_decompress.py against Quartus: decompress(compressed) must equal the
same design's uncompressed .rbf byte for byte, on every pair.

Pairs: corpus/cyclonev/<d>/{bitstream.compressed.rbf, bitstream.rbf} and the per-die SFL pairs in
tmp/cvcomp/sfl/ (both from scripts/cyclonev_compressed_pairs.py).  Also checks the uncompressed
side passes through unchanged.  Threads (python3.15t, no GIL).

Usage: python3.15t scripts/cyclonev_decompress_check.py [--corpus DIR] [--workers N]
Log: tmp/logs/cyclonev_decompress_check.log
"""
import argparse
import concurrent.futures as cf
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cyclonev_decompress as cd  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cyclonev_decompress_check.log"
log = logging.getLogger("cyclonev_decompress_check")


def check(name, cpath, upath):
    c, u = cpath.read_bytes(), upath.read_bytes()
    info = {}
    try:
        out = cd.decompress(c, info)
        same = cd.decompress(u)
    except cd.FormatError as e:
        return name, f"FormatError: {e}", info
    if out != u:
        i = next((k for k in range(min(len(out), len(u))) if out[k] != u[k]), min(len(out), len(u)))
        return name, f"DIFF first at {i:#x} (len {len(out)} vs {len(u)})", info
    if same != u:
        return name, "uncompressed input not passed through unchanged", info
    # Compressed-side length field: report 4*len(compressed) - field (rule not derived, #doc gaps).
    info["c_field_offset"] = 4 * len(c) - info["compressed_length_field"]
    return name, None, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(REPO / "corpus" / "cyclonev"))
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG, mode="w"), logging.StreamHandler(sys.stdout)])
    corpus = sorted(d for d in Path(a.corpus).iterdir() if (d / "bitstream.rbf").is_file())
    jobs = [("corpus", d.name, d / "bitstream.compressed.rbf", d / "bitstream.rbf")
            for d in corpus if (d / "bitstream.compressed.rbf").is_file()]
    missing = [d.name for d in corpus if not (d / "bitstream.compressed.rbf").is_file()]
    sfl = REPO / "tmp" / "cvcomp" / "sfl"
    jobs += [("sfl", p.name, p, p.with_name(p.name.replace(".compressed", "")))
             for p in sorted(sfl.glob("*.compressed.rbf"))]
    res = {"corpus": [0, 0], "sfl": [0, 0]}
    offsets = {}
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(check, n, c, u): kind for kind, n, c, u in jobs}
        for f in cf.as_completed(futs):
            kind = futs[f]
            name, err, info = f.result()
            res[kind][1] += 1
            if err:
                log.error("%s %s: %s", kind, name, err)
            else:
                res[kind][0] += 1
                offsets.setdefault(info["c_field_offset"], []).append(name)
                log.info("%s %s identical: len %d pram %dx%d cram %dx%d", kind, name,
                         info["length"], info["pram_frames"], info["pram_frame"],
                         info["cram_frames"], info["cram_frame"])
    for kind, (ok, n) in res.items():
        log.info("%s: %d/%d byte-identical", kind, ok, n)
    for off, names in sorted(offsets.items()):
        log.info("compressed length field = 4*len - %d: %d files (e.g. %s)", off, len(names), names[0])
    log.info("corpus designs with no compressed pair: %d %s", len(missing), missing[:10])
    return 0 if all(ok == n for ok, n in res.values()) and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
