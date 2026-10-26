#!/usr/bin/env python3.15t
"""Find per-FF control-select bits: within a LAB, FFs whose port P (CLK, CLRN, ENA) comes from
different LAB lines (RCF: BLK_CLK_BUF k / LAB_CONTROL_MUX k feeding the FF pin) must differ in
the select bit; FFs on the same line must agree.

- Candidate bits: per LE window as in cycloneiv_le_features (frames FX-34..FX+8, v +-3 around the
  LE, odd LEs mirrored).
- Score per candidate, over LABs with exactly 2 distinct lines on port P: the bit is a function of
  the line and differs between the two (a split).  Report best candidates with
  consistent / LABs, on the crc32-even half, checked on the odd half.

  python3.15t scripts/cycloneiv_lab_controls.py --designs 'rnd_l*'
Log tmp/logs/cycloneiv_lab_controls.log
"""
import argparse
import collections
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_le_features as lf  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_lab_controls")
PORTS = ["CLK", "CLRN", "ENA"]


def ff_lines(d):
    """{(x, y, le, port): line} with line = (TYPE, idx) of the element feeding the FF pin."""
    vo, out = d["vo"], {}
    for net, edges in d["rcf"].items():
        for s, t in edges:
            if t[0] != "SINK" or s[0] != "W":
                continue
            loc = rl.atom_xyn(vo, t[1])
            if loc is None or loc[0] != "FF":
                continue
            _k, x, y, n = loc
            out[(x, y, n // 2, t[2])] = (s[1], s[5])
    return out


def collect(name, geom):
    d = cc.load(name)
    lines = ff_lines(d)
    labs = collections.defaultdict(lambda: collections.defaultdict(list))
    for (x, y, le, port), line in lines.items():
        if port in PORTS:
            labs[(x, y, port)][line].append(le)
    rows = collections.defaultdict(list)   # port -> [(bitsA [nA, K], bitsB [nB, K])]
    for (x, y, port), by in labs.items():
        if len(by) != 2:
            continue
        groups = []
        for line, les in sorted(by.items()):
            b = [lf.le_bits(d["plane"], geom, x, y, le) for le in les]
            if any(v is None for v in b):
                break
            groups.append(np.stack(b))
        if len(groups) == 2:
            rows[port].append(tuple(groups))
    return name, rows


def split_ok(groups):
    """bool [K]: bit constant within each group and different between them."""
    a, b = groups
    ca, cb = a.all(0) | (~a).all(0), b.all(0) | (~b).all(0)
    return ca & cb & (a[0] != b[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--designs", default="rnd_l*")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_lab_controls.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = cc.designs(a.designs)
    geom = rl.one_geom(names)
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda n: collect(n, geom), names))
    nfr = lf.WIN_F[1] - lf.WIN_F[0]
    nvv = 2 * lf.WIN_V + 1
    pos = [(lf.WIN_F[0] + i // nvv, i % nvv - lf.WIN_V) for i in range(nfr * nvv)]
    for port in PORTS:
        tr = [g for n, r in res if rl.split_of(n, "even") for g in r.get(port, [])]
        te = [g for n, r in res if not rl.split_of(n, "even") for g in r.get(port, [])]
        if not tr:
            log.info("%s: no LAB with 2 lines", port)
            continue
        s = np.sum([split_ok(g) for g in tr], axis=0)
        best = np.argsort(-s)[:4]
        st = np.sum([split_ok(g) for g in te], axis=0) if te else np.zeros_like(s)
        log.info("%s: LABs with 2 lines train %d / held-out %d; best select bits: %s", port, len(tr), len(te),
                 [(pos[i], int(s[i]), int(st[i])) for i in best])
    return 0


if __name__ == "__main__":
    sys.exit(main())
