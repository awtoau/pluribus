#!/usr/bin/env python3.15t
"""Draft keep list for the EP4CGX150 corpus -> reference/corpus_keep.tsv (design, family, reason). Nothing is deleted here.

  python3.15t scripts/cycloneiv_corpus_keep.py      # log: tmp/logs/cycloneiv_corpus_keep.log
Rule (Dan, 2026-10-30): the corpus keeps (1) purpose-built decoder tests, (2) pair builds that are the only evidence of a rule with no
code source (M9K, MAC, PLL), (3) a seeded sample of N_SAMPLE designs per other family as regression tests. Everything else is rebuildable
from tag pre-one-die-20261030 and the generators.
"""
import csv
import hashlib
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO, "corpus", "cycloneiv")
OUT = os.path.join(REPO, "reference", "corpus_keep.tsv")
N_SAMPLE = 10               # per family (Dan: 50-100 is too many)
ALL = {"gxcanary": "canary", "gxt0": "tier0 self-loop"}
# per-subfamily caps (name prefix up to the 2nd underscore) inside a family; the rest of the family is seeded as usual
SUB_CAP = {"gx150": {"gx150_sp": 20, "gx150_rb": 30, "gx150_ffc": 30, "*": 1000},
           "gxhb": {"*": 6}}
ALWAYS = [f"gx150_rb_{i:03d}" for i in (0, 1, 2, 3, 4, 5, 7, 8)]       # gate rb set (survivors of rb_000..009)
N_BY = {"gxm9k": 40}        # M9K control pair builds are the only evidence of the port/mode rules (ledger SPECIMEN_ONLY)


def pick(names, n):
    return sorted(names, key=lambda x: hashlib.sha256(("seed1:" + x).encode()).hexdigest())[:n]


def main():
    fam = {}
    for d in sorted(os.listdir(ROOT)):
        if os.path.isdir(os.path.join(ROOT, d)):
            fam.setdefault(d.split("_")[0], []).append(d)
    rows = []
    for f, ds in sorted(fam.items()):
        if f in ALL:
            keep = [(d, ALL[f]) for d in ds]
        elif f in SUB_CAP:
            subs = {}
            for d in ds:
                subs.setdefault("_".join(d.split("_")[:2]), []).append(d)
            keep = []
            for sk, sv in sorted(subs.items()):
                n = SUB_CAP[f].get(sk, SUB_CAP[f]["*"])
                chosen = [d for d in ALWAYS if d in sv] + [d for d in pick([x for x in sv if x not in ALWAYS], max(0, n - len([d for d in ALWAYS if d in sv])))]
                why = ("gate rb set" if sk == "gx150_rb" else "purpose-built decoder test") if f == "gx150" else "pair builds, only evidence for MAC/PLL rules not yet found in code (ledger SPECIMEN_ONLY)"
                keep += [(d, f"{why} ({len(chosen)} of {len(sv)} {sk})") for d in chosen]
        else:
            n = N_BY.get(f, N_SAMPLE)
            keep = [(d, f"seeded regression sample ({n} of {len(ds)})") for d in pick(ds, n)]
        rows += [(d, f, why) for d, why in keep]
    have = {r[0] for r in rows}
    fast = os.path.join(REPO, "reference", "gate_fast.tsv")           # the fast gate set must exist in the kept corpus
    if os.path.exists(fast):
        for line in open(fast).read().splitlines()[1:]:
            d = line.split("\t")[0].strip()
            if d and d not in have and os.path.isdir(os.path.join(ROOT, d)):
                rows.append((d, d.split("_")[0], "fast gate member (reference/gate_fast.tsv)"))
    with open(OUT, "w") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["design", "family", "reason"])
        w.writerows(rows)
    total = sum(len(v) for v in fam.values())
    print(f"keep {len(rows)} of {total} designs; delete {total - len(rows)}")
    for f, ds in sorted(fam.items(), key=lambda kv: -len(kv[1])):
        print(f"{f:13}{len(ds):>6} -> {sum(1 for r in rows if r[1] == f):>5}")


if __name__ == "__main__":
    main()
