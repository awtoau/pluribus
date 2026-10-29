#!/usr/bin/env python3.15t
"""Find the CRAM bits of IO sites by usage correlation, with no tile geometry.

For an IO site S (IOOBUF_X<x>_Y<y>_N<n> / IOIBUF_...): designs that use S (positives) vs the rest.
A bit is a candidate when it is set in (almost) all positives and in at most NEG_MAX of the
negatives.  Output: per site the candidate (frame, v) list, positives / negatives counts.

  python3.15t scripts/cycloneiv_io_bits.py --designs 'gx150_sp_*' --kind IOOBUF --min-pos 8
Log tmp/logs/cycloneiv_io_bits.log; JSON tmp/cycloneiv/io_bits_<kind>.json
"""
import argparse
import collections
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402

log = logging.getLogger("cycloneiv_io_bits")
NEG_MAX = 0.03     # fraction of negative designs allowed to have the bit
POS_MIN = 0.95     # fraction of positive designs that must have it
LOC = re.compile(r"^(IOOBUF|IOIBUF)_X(\d+)_Y(\d+)_N(\d+)$")


def load_keys(name):
    d = cc.load(name)
    sites = collections.defaultdict(set)
    for a in d["vo"].atoms.values():
        m = LOC.match(a.get("location") or "")
        if m:
            sites[m.group(1)].add((int(m.group(2)), int(m.group(3)), int(m.group(4))))
    return name, d["plane"].keys, d["plane"].shape, sites


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--designs", default="gx150_sp_*")
    ap.add_argument("--kind", default="IOOBUF")
    ap.add_argument("--min-pos", type=int, default=8)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_io_bits.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = cc.designs(a.designs)
    with ThreadPoolExecutor(a.workers) as ex:
        data = list(ex.map(load_keys, names))
    nv = data[0][2][1]
    use = collections.defaultdict(list)
    for i, (_n, _k, _s, sites) in enumerate(data):
        for site in sites[a.kind]:
            use[site].append(i)
    cand_sites = sorted(s for s, v in use.items() if len(v) >= a.min_pos)
    log.info("%d designs, %d %s sites used at least once, %d with >= %d uses", len(data), len(use), a.kind,
             len(cand_sites), a.min_pos)
    out = {}
    for site in cand_sites:
        pos = use[site]
        posset = set(pos)
        cnt = collections.Counter()
        for i in pos:
            cnt.update(data[i][1].tolist())
        need = POS_MIN * len(pos)
        cand = np.array([k for k, c in cnt.items() if c >= need], dtype=np.int64)
        neg = [i for i in range(len(data)) if i not in posset]
        negc = np.zeros(len(cand), dtype=np.int32)
        for i in neg:
            negc += np.isin(cand, data[i][1], assume_unique=True)
        keep = cand[negc <= NEG_MAX * len(neg)]
        out["%d,%d,%d" % site] = {"pos": len(pos), "neg": len(neg),
                                  "bits": sorted((int(k // nv), int(k % nv)) for k in keep)}
        log.info("%s X%d Y%d N%d: pos %d, candidate bits %d: %s", a.kind, *site, len(pos), len(keep),
                 out["%d,%d,%d" % site]["bits"][:12])
    p = REPO / "tmp" / "cycloneiv" / f"io_bits_{a.kind}.json"
    p.write_text(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
