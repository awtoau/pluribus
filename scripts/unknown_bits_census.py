#!/usr/bin/env python3.15t
"""Census of bits the VENDOR sets that the open database cannot explain.

WHAT THIS MEASURES, AND WHAT IT DOES NOT
----------------------------------------
Decode every Diamond-built bitstream and count `unknown:` bits per tile type.
An unknown bit is one Diamond deliberately set and `bits.db` has no name for.

  * It IS a direct measure of database INCOMPLETENESS, over real vendor output,
    on data we already have -- no new fuzzing.
  * It is NOT a measure of CORRECTNESS.  A bit mapped to the WRONG parameter looks
    perfectly known, so this cannot see it.  Anyone quoting a low unknown count as
    evidence the database is right (as I did from a single design) is overreading
    it: this is a lower bound on what is missing and blind to what is wrong.

Why it is still worth having: it localises the hole.  #97's finding is that the
fuzzers decode with a decoder that FAILS on EFB-active designs, so parameters
needing such a design were recorded as having no bits.  If that is the mechanism,
unknown bits should CLUSTER in the tiles those designs touch -- EBR and its CIB --
rather than spread evenly.  A single design (V07) showed 91 of 152 in EBR/CIB_EBR.
This checks whether that holds across thousands.

The complementary test, which DOES measure correctness, is a per-parameter Diamond
round trip: vary one setting, rebuild, and confirm the expected enum appears and
nothing else changes.  #88 did exactly that for SEDGA (200/200 exact, zero unknown
bits in the SED tile).  That needs Diamond runs; this does not.

    scripts/unknown_bits_census.py [--limit N] [--workers N]

Logs to ./tmp/logs/unknown_bits_census.log; JSON to tmp/unknown_bits_census.json.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import glob
import json
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
LOG_DIR = REPO / "tmp/logs"


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("unknown_bits_census")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "unknown_bits_census.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def census_one(path):
    """Decode one bitstream; return (name, {tile_type: unknown_bits}, n_tiles)."""
    import native_config
    from ecp5_corpus_test import identify
    try:
        # Device from the bitstream's own IDCODE, never the default.  Passing no
        # device made this decode ECP5 sedga_* targets with MachXO2 geometry -- 204
        # failures, and #86 in miniature.  The IDCODE cross-check added in
        # c4ae53c3f is what turned that into a loud error instead of a mirrored
        # fabric, so the guard earned its place on its author.
        dev, _fam, _idc, _how = identify(path)
        text, _pb, _bram = (native_config.config_from_file(path, device=dev)
                            if dev else native_config.config_from_file(path))
    except Exception as exc:
        return (path, None, f"{type(exc).__name__}: {str(exc)[:90]}")
    per = collections.Counter()
    tiles = 0
    tile = None
    for line in text.splitlines():
        if line.startswith(".tile "):
            tile = line.split()[1].split(":")[-1]
            tiles += 1
        elif tile and "unknown" in line:
            per[tile] += 1
    return (path, dict(per), tiles)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="cap bitstreams (0 = all)")
    ap.add_argument("--workers", type=int,
                    default=max(1, (os.cpu_count() or 4) // 2))
    ap.add_argument("--json", default=str(REPO / "tmp/unknown_bits_census.json"))
    args = ap.parse_args()
    log = setup_logging()

    paths = sorted(glob.glob(str(REPO / "diamond-fuzz/targets/*/impl1/*.bit")))
    if args.limit:
        paths = paths[:args.limit]
    log.info("decoding %d Diamond-built bitstream(s), %d worker(s)", len(paths),
             args.workers)

    per_tile = collections.Counter()
    designs_with = collections.Counter()
    n_ok = n_fail = tot_unknown = 0
    # Processes, not threads: each worker holds its own decoder state and tile DB
    # view, which is the pattern the other parity harnesses use for the same reason.
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        for path, per, extra in pool.map(census_one, paths, chunksize=4):
            if per is None:
                n_fail += 1
                if n_fail <= 5:
                    log.error("  %s: %s", Path(path).parts[-3], extra)
                continue
            n_ok += 1
            for tile, n in per.items():
                per_tile[tile] += n
                designs_with[tile] += 1
                tot_unknown += n

    log.info("decoded %d, failed %d", n_ok, n_fail)
    log.info("total unknown bits: %d across %d tile type(s)", tot_unknown,
             len(per_tile))
    log.info("---- unknown bits by tile type ----")
    for tile, n in per_tile.most_common(25):
        log.info("  %-26s %8d bits   in %d design(s)", tile, n,
                 designs_with[tile])
    ebr = sum(n for t, n in per_tile.items() if "EBR" in t)
    log.info("")
    log.info("EBR-related tiles account for %d of %d unknown bits (%.0f%%)",
             ebr, tot_unknown, 100 * ebr / tot_unknown if tot_unknown else 0)
    log.info("Clustering supports the #97 mechanism (the fuzzers' decoder fails on "
             "EFB-active designs); an even spread would argue against it.")
    with open(args.json, "w") as fh:
        json.dump({"decoded": n_ok, "failed": n_fail,
                   "total_unknown": tot_unknown,
                   "by_tile": dict(per_tile),
                   "designs_with_tile": dict(designs_with)}, fh, indent=2,
                  sort_keys=True)
    log.info("results -> %s", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
