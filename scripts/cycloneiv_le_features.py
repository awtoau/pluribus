#!/usr/bin/env python3.15t
"""Find per-LE configuration bits (FF use and controls, LUT mode) by correlating post-fit .vo
features with CRAM bits around each LE, pooled over every LE site of every design.

- LE base: frame FX[X], v VY[Y] + DN[le] (cycloneiv_geom); odd LEs of a pair mirror v (as the LUT
  mask does).  Candidate bits: frames FX-WIN_F..FX+8, v offset -WIN_V..+WIN_V (mirrored).
- Features (per LE): lut, cin (sum_lutc_input=cin), ff, ena, sclr, sload, clrn, asdata (port
  driven, not the constant), clkinv (clk inverted), d_lut (D = this LE's combout).
  Empty LE sites count as all-false instances.
- Fit on the crc32-even half, report on the odd half: per feature the best bit (or bit pair as
  AND / OR) as matched / (matched + missing + extra) where missing = feature true, bit 0 and
  extra = bit 1, feature false.

  python3.15t scripts/cycloneiv_le_features.py --designs 'rnd_l*'
Log tmp/logs/cycloneiv_le_features.log; JSON tmp/cycloneiv/le_features_<die>.json
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
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_le_features")
WIN_F = (-34, 9)
WIN_V = 3
FEATS = ["lut", "cin", "ff", "ena", "sclr", "sload", "clrn", "asdata", "clkinv", "d_lut", "d_other"]
LOC = re.compile(r"^(LCCOMB|FF)_X(\d+)_Y(\d+)_N(\d+)$")


def conn(a, port):
    for p, _b, _d, net, inv, const in a["conns"]:
        if p == port:
            return net, inv, const
    return None, False, None


def le_features(vo):
    """{(x, y, le): {feature: bool}} for every LE with a placed comb or FF cell."""
    out = collections.defaultdict(dict)
    comb_out = {}
    for name, a in vo.atoms.items():
        m = LOC.match(a.get("location") or "")
        if not m:
            continue
        kind, x, y, n = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        le = n // 2
        f = out[(x, y, le)]
        if kind == "LCCOMB":
            f["lut"] = True
            f["cin"] = a["params"].get("sum_lutc_input") == "cin"
            net, _i, _c = conn(a, "combout")
            comb_out[(x, y, le)] = vo.canon(net) if net else None
        else:
            f["ff"] = True
            for port, idle in (("ena", "1"), ("sclr", "0"), ("sload", "0"), ("clrn", "1"), ("asdata", None)):
                net, inv, const = conn(a, port)
                f[port + "_inv"] = bool(inv and const is None and net is not None)
                f[port] = net is not None and const is None or (const is not None and idle is not None
                                                               and const != idle)
            net, inv, _c = conn(a, "clk")
            f["clkinv"] = bool(inv)
            dnet, _i, _c = conn(a, "d")
            f["_d"] = vo.canon(dnet) if dnet else None
    for k, f in out.items():
        f["d_lut"] = bool(f.get("ff") and f.get("_d") and f.get("_d") == comb_out.get(k))
        f["d_other"] = bool(f.get("ff") and not f["d_lut"])
        f.pop("_d", None)
    return out


def le_bits(plane, geom, x, y, le):
    f0, v0 = geom.anchor(x, y)
    v0 += geom.DN[le]
    s = -1 if le % 2 else 1
    nf, nv = plane.shape
    fa, fb = f0 + WIN_F[0], f0 + WIN_F[1]
    vs = [v0 + s * dv for dv in range(-WIN_V, WIN_V + 1)]
    if fa < 0 or fb > nf or min(vs) < 0 or max(vs) >= nv:
        return None
    ff, vv = np.meshgrid(np.arange(fa, fb), np.array(vs), indexing="ij")
    return plane.has(ff, vv).reshape(-1)


SUBSET = "any"     # any | ff | lut : which LEs form the instance set


def collect(name, geom):
    d = cc.load(name)
    feats = le_features(d["vo"])
    rows, fx = [], []
    touched = {(x, y) for (x, y, _le) in feats}
    for x in range(geom.xmax + 1):
        if geom.col_kind(x) != "LAB":
            continue
        for y in range(1, geom.ymax):
            if (x, y) not in touched:
                continue      # empty LABs add no information and 150k LEs per design of memory
            for le in range(16):
                b = le_bits(d["plane"], geom, x, y, le)
                if b is None:
                    continue
                f = feats.get((x, y, le), {})
                if SUBSET == "either" and not (f.get("lut") or f.get("ff")):
                    continue
                if SUBSET in ("ff", "lut") and not f.get(SUBSET):
                    continue
                rows.append(b)
                fx.append([bool(f.get(k)) for k in FEATS])
    return name, np.array(rows, dtype=bool), np.array(fx, dtype=bool)


def score(bits, y):
    m = int((bits & y).sum())
    miss = int((~bits & y).sum())
    extra = int((bits & ~y).sum())
    return m, miss, extra


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--designs", default="rnd_l*")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--subset", default="any", choices=["any", "ff", "lut", "either"])
    a = ap.parse_args()
    global SUBSET
    SUBSET = a.subset
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_le_features.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = cc.designs(a.designs)
    geom = rl.one_geom(names)
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda n: collect(n, geom), names))
    tr = [r for r in res if rl.split_of(r[0], "even")]
    te = [r for r in res if not rl.split_of(r[0], "even")]
    Xtr, Ytr = np.concatenate([r[1] for r in tr]), np.concatenate([r[2] for r in tr])
    Xte, Yte = np.concatenate([r[1] for r in te]), np.concatenate([r[2] for r in te])
    nfr = WIN_F[1] - WIN_F[0]
    nvv = 2 * WIN_V + 1
    pos = [(WIN_F[0] + i // nvv, i % nvv - WIN_V) for i in range(nfr * nvv)]
    log.info("LE instances: train %d (%d designs), test %d (%d designs); die %s", len(Xtr), len(tr), len(Xte),
             len(te), geom.die)
    out = {}
    for j, fname in enumerate(FEATS):
        y = Ytr[:, j]
        if y.sum() == 0:
            log.info("%-7s no positive instances", fname)
            continue
        tp = (Xtr & y[:, None]).sum(0)
        acc = tp / np.maximum(Xtr.sum(0) + y.sum() - tp, 1)   # matched / (matched + missing + extra)
        order = np.argsort(-acc)[:6]
        best = order[0]
        # best pair (AND / OR) among the top 6 single bits
        cand = [((int(best),), "bit", acc[best])]
        for i1 in order:
            for i2 in order:
                if i1 < i2:
                    for op, v in (("and", Xtr[:, i1] & Xtr[:, i2]), ("or", Xtr[:, i1] | Xtr[:, i2])):
                        cand.append(((int(i1), int(i2)), op, (v & y).sum() / max(int((v | y).sum()), 1)))
        idx, op, tracc = max(cand, key=lambda c: c[2])
        if op == "bit":
            pred = Xte[:, idx[0]]
        elif op == "and":
            pred = Xte[:, idx[0]] & Xte[:, idx[1]]
        else:
            pred = Xte[:, idx[0]] | Xte[:, idx[1]]
        m, miss, extra = score(pred, Yte[:, j])
        out[fname] = {"bits": [pos[i] for i in idx], "op": op, "train_acc": float(tracc),
                      "test": {"matched": m, "missing": miss, "extra": extra}}
        log.info("%-7s %-4s bits %-28s train score %.5f | held-out matched %d / (m %d + missing %d + extra %d) = %.2f%%",
                 fname, op, [pos[i] for i in idx], tracc, m, m, miss, extra, 100 * m / max(m + miss + extra, 1))
    p = REPO / "tmp" / "cycloneiv" / f"le_features_{geom.die}.json"
    p.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
