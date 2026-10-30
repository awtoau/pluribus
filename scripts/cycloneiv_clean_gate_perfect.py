#!/usr/bin/env python3.15t
"""Designs perfect per gate category (missing = extra = wrong = 0) from tmp/cycloneiv_clean/gate_<name>.json.

  python3.15t scripts/cycloneiv_clean_gate_perfect.py corpus_run14set_pins
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATS = ("pips", "nets", "lut_init", "register_clock", "pins")


def main(name):
    rows = [r for r in json.load(open(os.path.join(REPO, "tmp", "cycloneiv_clean", f"gate_{name}.json")))["rows"] if "error" not in r]
    ok = lambda r, c: r[c]["missing"] == r[c]["extra"] == r[c]["wrong"] == 0
    for c in CATS:
        print(f"{c:15s} perfect {sum(ok(r, c) for r in rows)} / {len(rows)}")
    print(f"{'ALL five':15s} perfect {sum(all(ok(r, c) for c in CATS) for r in rows)} / {len(rows)}")


if __name__ == "__main__":
    main(sys.argv[1])
