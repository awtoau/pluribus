#!/usr/bin/env python3.15t
"""Set-diff two `.bt` files (line order is irrelevant; r/s/i/o/m). Used by the native-vs-Mistral differential.

  python3.15t scripts/cyclonev_bt_diff.py A.bt B.bt [--show N]
"""
import argparse
import collections


def read(path):
    out = collections.defaultdict(set)
    for line in open(path):
        line = line.rstrip("\n")
        if line:
            out[line[0]].add(line)
    return out


def diff(a, b):
    res = {}
    for k in sorted(set(a) | set(b)):
        res[k] = (a.get(k, set()) - b.get(k, set()), b.get(k, set()) - a.get(k, set()), len(a.get(k, ())), len(b.get(k, ())))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--show", type=int, default=8)
    n = ap.parse_args()
    for k, (oa, ob, na, nb) in diff(read(n.a), read(n.b)).items():
        print(f"[{k}] A={na} B={nb} only_A={len(oa)} only_B={len(ob)}")
        for l in sorted(oa)[:n.show]:
            print("  A>", l)
        for l in sorted(ob)[:n.show]:
            print("  B>", l)
