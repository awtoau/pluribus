#!/usr/bin/env python3.15t
"""Symlink a corpus's gitignored build outputs from another checkout (e.g. main) into this one.

Worktrees get only the tracked src/ + design.toml; the builds stay in the checkout that made them.
Links are read-only references: nothing is written into the source checkout.

  python3.15t scripts/corpus_link_outputs.py --family cycloneiv --source /path/to/main/checkout
Log: tmp/logs/corpus_link_outputs.log
"""
import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
log = logging.getLogger("corpus_link_outputs")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", required=True)
    ap.add_argument("--source", required=True, type=Path)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "corpus_link_outputs.log"), logging.StreamHandler()):
        log.addHandler(h)
    src_root = a.source.resolve() / "corpus" / a.family
    dst_root = REPO / "corpus" / a.family
    if src_root == dst_root.resolve():
        log.error("source and destination are the same corpus")
        return 1
    made = 0
    for d in sorted(p for p in src_root.iterdir() if (p / "design.toml").exists()):
        dd = dst_root / d.name
        if not (dd / "design.toml").exists():
            continue   # not tracked here: skip rather than create an untracked design
        for f in d.iterdir():
            if f.name in ("src", "design.toml"):
                continue
            t = dd / f.name
            if t.exists() or t.is_symlink():
                continue
            t.symlink_to(f)
            made += 1
    log.info("linked %d outputs from %s", made, src_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
