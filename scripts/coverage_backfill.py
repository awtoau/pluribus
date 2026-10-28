#!/usr/bin/env python3.15t
"""Append a backfilled ledger line from a saved inventory JSON (docs/coverage-history.jsonl).

  python3.15t scripts/coverage_backfill.py <inventory.json> <commit> <ts-iso-offset>
source = "backfill@<commit>"; use only for a run whose output was saved and matches that commit's doc.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cycloneiv_bit_inventory as inv

out = json.load(open(sys.argv[1]))
full = inv.git("rev-parse", sys.argv[2])
inv.record(out, 24, 41 + 120 + 6024, 159, commit=full, ts=sys.argv[3], source=f"backfill@{full[:9]}", dirty=False)
