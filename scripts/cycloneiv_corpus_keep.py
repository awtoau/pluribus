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
ALL = {"gx150": "purpose-built decoder test (carry, FF controls, IO, header, geometry, gate set rb_*)",
       "gxhb": "only evidence for MAC/PLL rules not yet found in code (ledger SPECIMEN_ONLY)",
       "gxcanary": "canary", "gxt0": "tier0 self-loop"}
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
        else:
            n = N_BY.get(f, N_SAMPLE)
            keep = [(d, f"seeded regression sample ({n} of {len(ds)})") for d in pick(ds, n)]
        rows += [(d, f, why) for d, why in keep]
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
