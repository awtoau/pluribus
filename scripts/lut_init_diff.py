#!/usr/bin/env python3.15t
"""Multiset difference of canonical LUT INITs between an original decode and a rebuild (#127).

Shows which functions are missing and which are extra, so a lifter bug (an INIT that exists only
in the rebuild) can be traced instead of counted.

    python3.15t scripts/lut_init_diff.py ORIG.config NEW.config [--top 25]
Log: tmp/logs/lut_init_diff.log
"""
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import diamond_roundtrip as D  # noqa: E402

LOG = REPO / "tmp" / "logs" / "lut_init_diff.log"


def canon(cfg):
    fp = D.fingerprint(cfg)
    c = Counter()
    for k, n in fp["lut_inits"].items():
        c[D.canonical_lut(k)] += n
    return c


def main():
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 25
    a, b = canon(sys.argv[1]), canon(sys.argv[2])
    both = a & b
    miss, extra = a - b, b - a
    out = [f"orig {sum(a.values())} new {sum(b.values())} matched {sum(both.values())} "
           f"missing {sum(miss.values())} extra {sum(extra.values())}",
           "-- extra (in rebuild only):"]
    out += [f"  {n:4d}  {k}" for k, n in extra.most_common(top)]
    out += ["-- missing (in original only):"]
    out += [f"  {n:4d}  {k}" for k, n in miss.most_common(top)]
    text = "\n".join(out)
    print(text)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(text + "\n")


if __name__ == "__main__":
    main()
