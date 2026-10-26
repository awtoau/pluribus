#!/usr/bin/env python3.15t
"""Per-FF configuration fields of an LE from the register-control corpus.

For every FF (post-fit .vo = label, CRAM window around its LE = features), greedy forward
selection of LE-window bits: the next bit is the one that most raises the accuracy of the
decision table "tuple of selected bits -> majority label" on the crc32-even designs; the table is
then scored on the odd designs (accuracy plus matched / missing / extra for the positive class).

Labels: d_direct (D not from the LE's LUT), sload / sclr / clrn used (pin not tied to its idle
constant), ena used, clk_inv.  Parity of the LE index is kept apart (the odd LEs mirror).

  python3.15t scripts/cycloneiv_ff_fields.py --designs 'gx150_ffc_*' [--bits 5]
Log tmp/logs/cycloneiv_ff_fields.log; JSON tmp/cycloneiv/ff_fields.json
"""
import argparse
import collections
import json
import logging
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_le_features as lf  # noqa: E402
import cycloneiv_le_locate as ll  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_ff_fields")
LABELS = ["d_direct", "sload", "sclr", "clrn", "ena", "clk_inv"]


def collect(name, geom):
    d = cc.load(name)
    feats = lf.le_features(d["vo"])
    rows, labs, les = [], [], []
    for (x, y, le), f in feats.items():
        if not f.get("ff"):
            continue
        b = lf.le_bits(d["plane"], geom, x, y, le)
        if b is None:
            continue
        rows.append(b)
        labs.append([not f["d_lut"], f["sload"], f["sclr"], f["clrn"], f["ena"], f["clkinv"]])
        les.append(le)
    return name, np.array(rows, dtype=bool), np.array(labs, dtype=bool), np.array(les)


def table_acc(X, y, cols):
    key = np.zeros(len(X), dtype=np.int64)
    for c in cols:
        key = key * 2 + X[:, c]
    tab = collections.defaultdict(lambda: [0, 0])
    for k, v in zip(key, y):
        tab[int(k)][int(v)] += 1
    maj = {k: int(v[1] > v[0]) for k, v in tab.items()}
    return maj, sum(max(v) for v in tab.values()) / max(len(y), 1)


def predict(X, cols, maj):
    key = np.zeros(len(X), dtype=np.int64)
    for c in cols:
        key = key * 2 + X[:, c]
    return np.array([maj.get(int(k), 0) for k in key], dtype=bool)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--designs", default="gx150_ffc_*")
    ap.add_argument("--bits", type=int, default=5)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_ff_fields.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = cc.designs(a.designs)
    geom = rl.one_geom(names)
    res = [collect(n, geom) for n in names]
    nvv = 2 * lf.WIN_V + 1
    pos = [(lf.WIN_F[0] + i // nvv, i % nvv - lf.WIN_V) for i in range(len(lf.WIN_F) * 0 + (lf.WIN_F[1] - lf.WIN_F[0]) * nvv)]
    maskpos = set(ll.DK)
    cand = [i for i, p in enumerate(pos) if p not in maskpos]
    out = {}
    for par in (0, 1):
        tr = [r for r in res if rl.split_of(r[0], "even")]
        te = [r for r in res if not rl.split_of(r[0], "even")]

        def stack(rs, k):
            xs = np.concatenate([r[1] for r in rs])
            ys = np.concatenate([r[2] for r in rs])
            ls = np.concatenate([r[3] for r in rs])
            m = (ls % 2) == par
            return xs[m], ys[m][:, k]
        for k, lab in enumerate(LABELS):
            Xtr, ytr = stack(tr, k)
            Xte, yte = stack(te, k)
            if ytr.sum() < 10:
                log.info("parity %d %-8s too few positives (%d)", par, lab, int(ytr.sum()))
                continue
            sel = []
            for _ in range(a.bits):
                best = None
                for c in cand:
                    if c in sel:
                        continue
                    _m, acc = table_acc(Xtr, ytr, sel + [c])
                    if best is None or acc > best[0]:
                        best = (acc, c)
                sel.append(best[1])
                if best[0] >= 0.9999:
                    break
            maj, acc = table_acc(Xtr, ytr, sel)
            pred = predict(Xte, sel, maj)
            m = int((pred & yte).sum())
            miss = int((~pred & yte).sum())
            extra = int((pred & ~yte).sum())
            log.info("parity %d %-8s base rate %.3f; bits %s; train acc %.4f; held-out positives %d: matched %d / "
                     "(matched %d + missing %d + extra %d) = %.2f%%", par, lab, ytr.mean(), [pos[c] for c in sel],
                     acc, int(yte.sum()), m, m, miss, extra, 100 * m / max(m + miss + extra, 1))
            out[f"{par}:{lab}"] = {"bits": [pos[c] for c in sel], "table": {str(k_): v for k_, v in maj.items()}}
    (REPO / "tmp" / "cycloneiv" / "ff_fields.json").write_text(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
