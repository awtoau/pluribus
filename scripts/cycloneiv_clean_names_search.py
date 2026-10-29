#!/usr/bin/env python3.15t
"""RCF type string -> routing.ddb element enum, by edge consistency over RCF net trees (A7, #165).  0 builds.

Prediction: every RCF type resolves to one enum E with >= 99 % of its names unique under exact (E, x, y, z, index)
and >= 99 % of its parent -> child tree edges inside the parent's ddb fan-out; runner-up enum < 50 %.
Refutation: any type with < 99 % at the best enum, or a runner-up within 5 points, is reported as not derived.
Inputs: corpus routing.rcf files (our own build outputs) and tmp/ddb/stingray4_rt_fanout.npz.  No seed table.
Output: tmp/logs/cycloneiv_clean_names_search.json (consumed by cycloneiv_clean_names_table.py).
"""
import collections
import json
import os
import re
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from lifters.cycloneiv_clean import ddb  # noqa: E402

NAME = re.compile(r"^([A-Z][A-Z0-9_]*):X(\d+)Y(\d+)S(\d+)I(\d+)$")
LABEL = re.compile(r"^label = (\S+), (\S+);$")
BRANCH = re.compile(r"^branch_point = (\S+);$")
OUT = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_names_search.json")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_names_search.log")


def parse_rcf(path):
    """-> (edges [(parent_name, child_name)], first-of-net names, all names); names are (type, x, y, z, i)."""
    edges, firsts, names = [], [], set()
    alias, prev, fresh = {}, None, True
    def tup(s):
        m = NAME.match(s)
        return (m[1], int(m[2]), int(m[3]), int(m[4]), int(m[5])) if m else None
    for line in open(path):
        s = line.strip()
        if s.startswith("signal_name"):
            alias, prev, fresh = {}, None, True
            continue
        el = None
        m = LABEL.match(s)
        if m:
            alias[m[1]] = tup(m[2]); el = alias[m[1]]
        elif BRANCH.match(s):
            prev = alias.get(BRANCH.match(s)[1]); fresh = False
            continue
        elif s.startswith("dest ="):
            prev = None; fresh = False
            continue
        else:
            m = NAME.match(s.rstrip(";"))
            if m:
                el = tup(s.rstrip(";"))
        if el is None:
            continue
        names.add(el)
        if prev is None:
            firsts.append(el)
        else:
            edges.append((prev, el))
        prev = el
    return edges, firsts, names


def main():
    rt = ddb.Routing()
    keys = rt.element_keys()
    order = np.argsort(keys, kind="stable")
    sk = keys[order]
    enums = sorted(set(int(e) for e in rt.enum[rt.tpl[rt.tpl >= 0]]))
    fan = {}

    def fanset(r):
        if r not in fan:
            fan[r] = set(rt.fanout(r).tolist())
        return fan[r]

    def resolve(e, names):
        q = np.array([ddb.element_key(e, x, y, z, i) for _, x, y, z, i in names], np.int64)
        lo, hi = np.searchsorted(sk, q, "left"), np.searchsorted(sk, q, "right")
        rec = np.where(hi - lo == 1, order[np.minimum(lo, len(order) - 1)], -1)
        return rec, hi - lo

    cdir = os.path.join(REPO, "corpus", "cycloneiv")
    m4k = [d for d in sorted(os.listdir(cdir)) if d.startswith("gxm9k_") and "M4K_BUFFER" in open(os.path.join(cdir, d, "routing.rcf")).read()]
    designs = [f"gx150_rb_{n:03d}" for n in range(30)] + m4k[:10]
    E, F, N = [], [], set()
    for d in designs:
        e, f, n = parse_rcf(os.path.join(REPO, "corpus", "cycloneiv", d, "routing.rcf"))
        E += e; F += f; N |= n
    types = sorted({n[0] for n in N})
    byt = {t: sorted(n for n in N if n[0] == t) for t in types}
    uniq = {}   # (t, e) -> fraction of distinct names unique
    for t in types:
        for e in enums:
            _, c = resolve(e, byt[t])
            uniq[(t, e)] = float((c == 1).mean())
    cand = {t: [e for e in enums if uniq[(t, e)] >= 0.5] for t in types}
    # edge groups by (parent type, child type), de-duplicated
    grp = collections.defaultdict(set)
    for p, c in E:
        grp[(p[0], c[0])].add((p, c))
    grp = {k: sorted(v) for k, v in grp.items()}

    def edge_score(tp, ep, tc, ec):
        ed = grp[(tp, tc)]
        rp, _ = resolve(ep, [p for p, _ in ed]); rc, _ = resolve(ec, [c for _, c in ed])
        ok = sum(1 for a, b in zip(rp.tolist(), rc.tolist()) if a >= 0 and b >= 0 and b in fanset(a))
        return ok, len(ed)

    # pair scores over candidate enum pairs
    pair = {}
    for (tp, tc), ed in grp.items():
        for ep in cand[tp]:
            for ec in cand[tc]:
                pair[(tp, ep, tc, ec)] = edge_score(tp, ep, tc, ec)
    # per-type score of enum e = best partner-consistent fraction over all incident groups (max over partner candidates)
    res = {}
    for t in types:
        sc = {}
        for e in cand[t]:
            ok = tot = 0
            for (tp, tc) in grp:
                if t not in (tp, tc):
                    continue
                if tp == t:
                    best = max((pair[(tp, e, tc, ec)] for ec in cand[tc]), key=lambda v: v[0], default=(0, len(grp[(tp, tc)])))
                else:
                    best = max((pair[(tp, ep, tc, e)] for ep in cand[tp]), key=lambda v: v[0], default=(0, len(grp[(tp, tc)])))
                ok += best[0]; tot += best[1]
            sc[e] = (ok, tot)
        rank = sorted(sc.items(), key=lambda kv: (-(kv[1][0] / max(kv[1][1], 1)), -uniq[(t, kv[0])]))
        bu = max(enums, key=lambda e: uniq[(t, e)])
        res[t] = dict(best_unique=(bu, uniq[(t, bu)]), designs=len(designs), names=len(byt[t]), edges=rank[0][1][1] if rank else 0,
                      ranked=[(e, ok, tot, uniq[(t, e)]) for e, (ok, tot) in rank[:3]],
                      firsts=sum(1 for f in F if f[0] == t))
    # phase B: restrict to edges whose partner type is derived (phase-A ratio >= 99 %), partner enum fixed
    core = {t: v["ranked"][0][0] for t, v in res.items() if v["ranked"] and v["ranked"][0][2] and v["ranked"][0][1] / v["ranked"][0][2] >= 0.99}
    for t in types:
        sc = {}
        for e in cand[t]:
            ok = tot = 0
            for (tp, tc) in grp:
                if t == tp and tc in core:
                    r = pair.get((tp, e, tc, core[tc]), (0, len(grp[(tp, tc)])))
                elif t == tc and tp in core:
                    r = pair.get((tp, core[tp], tc, e), (0, len(grp[(tp, tc)])))
                else:
                    continue
                ok += r[0]; tot += r[1]
            sc[e] = (ok, tot)
        rank = sorted(sc.items(), key=lambda kv: (-(kv[1][0] / max(kv[1][1], 1)), -uniq[(t, kv[0])]))
        res[t]["phaseB"] = [(e, ok, tot, uniq[(t, e)]) for e, (ok, tot) in rank[:3]]
        res[t]["unique_cands"] = sum(1 for e in enums if uniq[(t, e)] >= 0.99)
    json.dump(res, open(OUT, "w"), indent=1)
    with open(LOG, "w") as lf:
        for t in types:
            lf.write(f"{t} {res[t]}\n")
    for t in types:
        print(t, res[t])


main()
