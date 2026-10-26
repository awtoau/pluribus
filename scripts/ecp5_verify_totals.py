#!/usr/bin/env python3.15t
"""Sum the per-design round-trip numbers in ecp5_verify_all logs (branch vs main).

    python3.15t scripts/ecp5_verify_totals.py tmp/logs/verify_branch.out tmp/logs/verify_main.out

Only designs present in ALL logs are summed (a design still running or failed
reference generation in one run would skew the comparison).  Logs to
./tmp/logs/ecp5_verify_totals.log.
"""
import os
import re
import sys

PATS = {
    "lut_sites_recovered": r"\[1\] LUT placement: (\d+)/(\d+) truth sites",
    "lut_absent": r"(\d+) recovered sites absent from truth",
    "lut_wrong": r"\[2\] LUT function: .* (\d+) WRONG",
    "ff_sites": r"\[3\] FF placement: (\d+)/(\d+)",
    "ff_sd_mismatch": r"\[4\] FF SD .*: \d+/\d+ matched, (\d+) mismatched",
    "ff_regset_mismatch": r"\[4b\] FF REGSET .*: \d+/\d+ matched, (\d+) mismatched",
    "net_consistent": r"CONSISTENT .*: (\d+) \(",
    "net_split": r"SPLIT .*: +(\d+)",
    "net_fused": r"FUSED .*: +(\d+)",
    "fanin": r"LUT fan-in .*: (\d+) match, (\d+) unmodelled-element gaps, (\d+) WRONG, (\d+) unattributable",
}


def parse(path):
    designs, cur = {}, None
    for ln in open(path):
        m = re.search(r"=== (\S+) \(", ln)
        if m:
            cur = designs.setdefault(m.group(1), {})
            continue
        if cur is None:
            continue
        for k, p in PATS.items():
            m = re.search(p, ln)
            if m:
                cur[k] = tuple(int(x) for x in m.groups())
    return designs


def main():
    paths = sys.argv[1:]
    runs = [parse(p) for p in paths]
    common = sorted(set.intersection(*[set(r) for r in runs]))
    os.makedirs("tmp/logs", exist_ok=True)
    out = open("tmp/logs/ecp5_verify_totals.log", "w")

    def say(s):
        print(s)
        out.write(s + "\n")

    say(f"designs in all runs: {len(common)} ({', '.join(f'{p}={len(r)}' for p, r in zip(paths, runs))})")
    for p, r in zip(paths, runs):
        tot = {}
        for d in common:
            for k, v in r[d].items():
                t = tot.setdefault(k, [0] * len(v))
                for i, x in enumerate(v):
                    t[i] += x
        say(f"== {p}")
        for k, v in tot.items():
            say(f"  {k}: {v}")


if __name__ == "__main__":
    main()
