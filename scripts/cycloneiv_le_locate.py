#!/usr/bin/env python3.15t
"""Locate LAB tiles in the CRAM of any Cyclone IV die from ordinary builds (no per-site sweeps).

Uses the EP4CE6 LE layout rule (cycloneiv_le_model), which is per LAB and assumed die-independent:
mask bit k of LE N at frame F - k//2, and within one bit-lane at byte B + DN[N] + s*dv(k)
(s = -1 for odd LE pairs).  Per LAB tile with >= MIN_LUTS placed LUTs (post-fit .vo: location +
lut_mask), search every (frame F, lane, byte B) for the one where all predicted mask bits equal the
CRAM.  A unique hit is the tile's anchor; 0 or >1 hits are reported.

  python3.15t scripts/cycloneiv_le_locate.py DESIGN [DESIGN ...] [--json out.json]
Log tmp/logs/cycloneiv_le_locate.log
"""
import argparse
import collections
import json
import logging
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_decompress as cd  # noqa: E402

log = logging.getLogger("cycloneiv_le_locate")
MIN_LUTS = 6
# EP4CE6 per-LAB rule (docs/cycloneiv-bitstream.md "LE address model"): v offset of LE N/2, and per
# mask bit k (frame delta, v delta).  In one bit-lane v == byte.
DN = [0, -3, -8, -11, -16, -19, -24, -27, -38, -41, -46, -49, -54, -57, -62, -65]
DK = [(0, 0), (0, -1), (-1, -1), (-1, 0), (-2, 0), (-2, -1), (-3, -1), (-3, 0),
      (-4, 0), (-4, -1), (-5, -1), (-5, 0), (-6, 0), (-6, -1), (-7, -1), (-7, 0)]
LOC = re.compile(r"^LCCOMB_X(\d+)_Y(\d+)_N(\d+)$")


def raw_planes(rbf):
    """bool [frame, lane, byte] of the data part of every frame (CRC bytes excluded on CRAM)."""
    info = {}
    u = cd.decompress(rbf, info)
    f, r, n = info["frame"], info["periphery_frames"], info["cram_frames"]
    nb = f - 2
    arr = np.zeros((r + n, 8, nb), dtype=bool)
    for fr in range(1, r + n):
        base = cd.PREAMBLE + fr * f
        chunk = np.frombuffer(u[base:base + nb], dtype=np.uint8)
        bits = np.unpackbits(chunk, bitorder="little").reshape(nb, 8)
        arr[fr] = bits.T.astype(bool)
    return arr


def constraints(luts):
    """luts: [(N, mask)] -> [(df, db, val)] relative to the N0 mask-bit-0 position."""
    out = []
    for n, mask in luts:
        s = -1 if (n // 2) % 2 else 1
        for k in range(16):
            df, dv = DK[k]
            out.append((df, DN[n // 2] + s * dv, bool(mask >> k & 1)))
    return out


def locate(P, cons):
    """All (F, lane, B) where every constraint holds."""
    nfr, _, nb = P.shape
    dfs = [c[0] for c in cons]
    dbs = [c[1] for c in cons]
    f_lo, f_hi = -min(dfs), nfr - max(0, max(dfs))
    b_lo, b_hi = -min(dbs), nb - max(0, max(dbs))
    hits = []
    for lane in range(8):
        L = P[:, lane, :]
        ok = np.ones((f_hi - f_lo, b_hi - b_lo), dtype=bool)
        for df, db, val in sorted(cons, key=lambda c: not c[2]):
            sl = L[f_lo + df:f_hi + df, b_lo + db:b_hi + db]
            ok &= sl if val else ~sl
            if not ok.any():
                break
        for fi, bi in np.argwhere(ok):
            hits.append((int(fi + f_lo), lane, int(bi + b_lo)))
    return hits


def tiles_of(vo):
    t = collections.defaultdict(list)
    for a in vo.atoms.values():
        if a["type"] != "cycloneive_lcell_comb" or a["params"].get("sum_lutc_input") != "datac":
            continue
        m = LOC.match(a.get("location") or "")
        if not m:
            continue
        x, y, n = map(int, m.groups())
        mask = int(a["params"]["lut_mask"].split("'h")[1], 16)
        t[(x, y)].append((n, mask))
    return t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("designs", nargs="+")
    ap.add_argument("--json", default=str(REPO / "tmp" / "cycloneiv" / "le_locate.json"))
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_le_locate.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    res = {}
    for name in a.designs:
        P = raw_planes((cc.CORPUS / name / "bitstream.rbf").read_bytes())
        vo = cc.load_vo(name)
        uniq = amb = none = 0
        for (x, y), luts in sorted(tiles_of(vo).items()):
            if len(luts) < MIN_LUTS:
                continue
            hits = locate(P, constraints(luts))
            key = f"{x},{y}"
            if len(hits) == 1:
                uniq += 1
                res.setdefault(key, []).append(hits[0])
            elif hits:
                amb += 1
            else:
                none += 1
                log.info("%s X%d Y%d: no position fits %d LUTs", name, x, y, len(luts))
        log.info("%s: tiles located uniquely %d, ambiguous %d, none %d", name, uniq, amb, none)
    conflicts = {k: v for k, v in res.items() if len(set(map(tuple, v))) > 1}
    log.info("tiles %d, conflicting across designs %d", len(res), len(conflicts))
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps({k: v[0] for k, v in res.items()}, indent=0))
    return 0 if not conflicts else 1


if __name__ == "__main__":
    sys.exit(main())
