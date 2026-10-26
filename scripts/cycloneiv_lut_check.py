#!/usr/bin/env python3.15t
"""Decode every placed LUT mask from the CRAM with the die geometry and compare with the post-fit
.vo lut_mask, per design.  Per mask bit: matched / missing (site off the geometry) / wrong.

- Mask bit k of LE (X, Y, le): frame FX[X] + df(k), v = VY[Y] + DN[le] + s*dv(k), s = -1 for odd
  LEs (EP4CE6 LE model, cycloneiv_le_locate.DK).
- Arithmetic-mode cells (sum_lutc_input = cin) are scored too, as their own row.

  python3.15t scripts/cycloneiv_lut_check.py --designs 'gx150_*'
Log tmp/logs/cycloneiv_lut_check.log
"""
import argparse
import collections
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_le_locate as ll  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_lut_check")
LOC = re.compile(r"^LCCOMB_X(\d+)_Y(\d+)_N(\d+)$")


def decode_mask(plane, geom, x, y, le):
    if x not in geom.FX or geom.col_kind(x) != "LAB":
        return None
    m = 0
    for k, (df, dv) in enumerate(ll.DK):
        if rl.le_bit(plane, geom, x, y, le, df, dv):
            m |= 1 << k
    return m


def check(name, geom):
    d = cc.load(name)
    c = collections.Counter()
    for a in d["vo"].atoms.values():
        if a["type"] != "cycloneive_lcell_comb":
            continue
        mm = LOC.match(a.get("location") or "")
        if not mm:
            continue
        x, y, n = map(int, mm.groups())
        mode = "cin" if a["params"].get("sum_lutc_input") == "cin" else "datac"
        want = int(a["params"]["lut_mask"].split("'h")[1], 16)
        got = decode_mask(d["plane"], geom, x, y, n // 2)
        if got is None:
            c[(mode, "missing")] += 16
            continue
        diff = bin(got ^ want).count("1")
        c[(mode, "wrong")] += diff
        c[(mode, "matched")] += 16 - diff
        c[(mode, "cells")] += 1
        c[(mode, "cells_exact")] += diff == 0
    return name, c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--designs", default="gx150_*")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_lut_check.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = cc.designs(a.designs)
    geom = rl.one_geom(names)
    tot = collections.Counter()
    bad = []
    with ThreadPoolExecutor(a.workers) as ex:
        for name, c in ex.map(lambda n: check(n, geom), names):
            tot.update(c)
            if c[("datac", "wrong")] + c[("cin", "wrong")] + c[("datac", "missing")] + c[("cin", "missing")]:
                bad.append(name)
    log.info("die %s, %d designs (%s); designs with any wrong/missing bit: %d", geom.die, len(names), a.designs, len(bad))
    for mode in ("datac", "cin"):
        m, w, miss = tot[(mode, "matched")], tot[(mode, "wrong")], tot[(mode, "missing")]
        log.info("%-5s cells %d (exact %d); mask bits matched %d / (matched %d + missing %d + wrong %d) = %.4f%%",
                 mode, tot[(mode, "cells")], tot[(mode, "cells_exact")], m, m, miss, w, 100 * m / max(m + w + miss, 1))
    if bad:
        log.info("first designs with errors: %s", bad[:10])
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
