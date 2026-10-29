#!/usr/bin/env python3.15t
"""Progress ledger for the Cyclone IV recovery: counts what we KNOW, beside the die coverage line.

  python3.15t scripts/progress_ledger.py [--no-record]   # append a row, print deltas, rebuild reports/coverage.html
Data: databases/cycloneiv/gx150.db (evidence, claims, expectations, unknowns) + last row of docs/coverage-history.jsonl.
Why: die coverage only moves when cells are counted; specimen pairs, single cells and tables move first.
Log tmp/logs/progress_ledger.log.
"""
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "databases/cycloneiv/gx150.db"
LEDGER = REPO / "docs/progress-history.jsonl"
COVER = REPO / "docs/coverage-history.jsonl"
OUT = REPO / "reports/coverage.html"
LOG = REPO / "tmp/logs/progress_ledger.log"
# evidence source_ref prefix -> bucket
BUCKETS = (("bit_hunter", "bit hunter"), ("lab_modes", "LAB ports/fan/pswap"), ("cycloneiv_ctrl", "control lines"),
           ("cycloneiv_m9k", "M9K"), ("evidence/cycloneiv/cycloneiv_m9k", "M9K"), ("tmp/cycloneiv_m9k", "M9K"),
           ("evidence/cycloneiv/cycloneiv_forced", "forced routing"), ("sources/", "third-party images"))
# metric key -> (label, higher is better)
METRICS = {
    "single_cell_pairs": ("single-cell pairs (n_objects = 1)", True),
    "pairs_bit hunter": ("pairs: bit hunter", True), "pairs_LAB ports/fan/pswap": ("pairs: LAB ports/fan/pswap", True),
    "pairs_control lines": ("pairs: control lines", True), "pairs_M9K": ("pairs: M9K", True),
    "pairs_forced routing": ("pairs: forced routing", True), "pairs_other": ("pairs: other", True),
    "pairs_total": ("specimen pairs, all", True), "derived_tables": ("derived tables (maps, laws)", True),
    "claims_confirmed": ("claims: measured, confirmed", True), "claims_open": ("claims: open", False),
    "claims_statistical": ("claims: statistical tier", False), "expectations": ("expectations (predictions)", None),
    "unknowns": ("seriously-unknown rows", False), "die_verified": ("die bits verified (inventory)", True),
    "die_evidence": ("die bits with evidence (inventory)", True), "die_unknown": ("die bits unknown (inventory)", False),
}


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def bucket(ref):
    for pre, name in BUCKETS:
        if (ref or "").startswith(pre):
            return name
    return "other"


def measure():
    c = sqlite3.connect(DB)
    m = dict.fromkeys(METRICS, 0)
    for kind, ref, n in c.execute("select kind, source_ref, n_objects from evidence"):
        if kind == "derived-table":
            m["derived_tables"] += 1
        if kind != "specimen-pair":
            continue
        m["pairs_total"] += 1
        m["pairs_" + bucket(ref)] += 1
        m["single_cell_pairs"] += n == 1
    for tier, status, n in c.execute("select tier, status, count(*) from claims group by 1, 2"):
        m["claims_confirmed"] += n if (tier, status) == ("measured", "confirmed") else 0
        m["claims_open"] += n if status == "open" and tier != "statistical" else 0
        m["claims_statistical"] += n if tier == "statistical" else 0
    m["expectations"] = c.execute("select count(*) from expectations").fetchone()[0]
    m["unknowns"] = c.execute("select count(*) from unknowns").fetchone()[0]
    rows = [json.loads(line) for line in open(COVER) if line.strip()]
    if rows:
        for k in ("verified", "evidence", "unknown"):
            m["die_" + k] = rows[-1][k]
    return m


def commit():
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def main():
    rows = [json.loads(line) for line in open(LEDGER) if line.strip()] if LEDGER.exists() else []
    row = dict(ts=datetime.now().astimezone().isoformat(timespec="seconds"), commit=commit(), m=measure())
    if "--no-record" not in sys.argv:
        with open(LEDGER, "a") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    rows.append(row)
    prev = rows[-2] if len(rows) > 1 else None
    for k, (label, _) in METRICS.items():
        d = row["m"][k] - (prev["m"][k] if prev else row["m"][k])
        log(f"{label:45s} {row['m'][k]:>12,} {d:+,}")
    subprocess.run([sys.executable, str(REPO / "scripts/coverage_page_build.py"), str(OUT)], check=True)
    log(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
