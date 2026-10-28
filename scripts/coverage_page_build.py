#!/usr/bin/env python3.15t
"""Build the Cyclone IV coverage review page from docs/coverage-history.jsonl.

  python3.15t scripts/coverage_page_build.py <out.html>
Template scripts/coverage_page.template.html; data = ledger + milestone commits (git log). Log tmp/logs/coverage_page_build.log.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# milestones in recovery order; status text says why a commit has no data point
MILESTONES = [("70b88c5c7", "LUT INIT oracle compare (301 designs)"), ("58e2f6efa", "specimen fuzzer + AFX fix"),
              ("ae99442a5", "exact specimens merged"), ("435d32a54", "first forced specimens"),
              ("00b522779", "routing.ddb decoded"), ("d3604d876", "ddb edge map"),
              ("18eedf2a0", "LOCAL_LINE grid in 4 LABs"), ("2ad8dd8c9", "bit inventory")]


def git(*a):
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True, check=True).stdout.strip()


rows = [json.loads(l) for l in open(REPO / "docs/coverage-history.jsonl") if l.strip()]
by = {r["commit"][:9]: r for r in rows}
slots = {}
for h, what in MILESTONES + [(r["commit"][:9], "") for r in rows]:
    full = git("rev-parse", h)
    slots[h] = dict(hash=h, ts=git("log", "-1", "--format=%ad", "--date=iso-strict", full),
                    subject=git("log", "-1", "--format=%s", full), what=what, row=h in by)
slots = sorted(slots.values(), key=lambda s: s["ts"])
for s in slots:
    s["why_missing"] = None if s["row"] else "inventory script did not exist at this commit (first committed in 2ad8dd8c9); not fabricated"
data = dict(ledger=rows, slots=slots)
tpl = (REPO / "scripts/coverage_page.template.html").read_text()
Path(sys.argv[1]).write_text(tpl.replace("/*DATA*/null", json.dumps(data, separators=(",", ":"))))
print("wrote", sys.argv[1], len(rows), "ledger rows,", len(slots), "slots")
