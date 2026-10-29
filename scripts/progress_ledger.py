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
    "claims_statistical": ("claims: statistical tier", False), "claims_suspect": ("claims: suspect or refuted", False), "expectations": ("expectations (predictions)", None),
    "unknowns": ("seriously-unknown rows", False),     "die_verified": ("die bits verified (oracle)", True), "die_measured": ("die bits measured", True),
    "die_sampled": ("die bits verified-by-sampling", True), "die_predicted": ("die bits pattern-predicted", None),
    "die_decoded": ("die bits decoded-untested", None), "die_suspect": ("die bits suspect", False),
    "die_refuted": ("die bits refuted", False), "die_unknown": ("die bits unknown, set in some design (live)", False),
    "die_projected": ("die bits unknown, never set in any held design (projected unused)", None),
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
    m["claims_suspect"] = c.execute("select count(*) from claims where status in ('suspect', 'refuted')").fetchone()[0]
    m["expectations"] = c.execute("select count(*) from expectations").fetchone()[0]
    m["unknowns"] = c.execute("select count(*) from unknowns").fetchone()[0]
    rows = [json.loads(line) for line in open(COVER) if line.strip()]
    if rows:
        for k in ("verified", "measured", "sampled", "predicted", "decoded", "suspect", "refuted", "unknown", "projected"):
            m["die_" + k] = rows[-1].get(k, 0)    # older ledger rows lack the split tiers: 0
    return m


def backfill(rows):
    """Hourly rows before the first live row: pair counts from evidence.created_at (migrated rows count at their
    migration time), die counts from the coverage ledger. Claim metrics are absent, not zero."""
    c = sqlite3.connect(DB)
    cov = [json.loads(line) for line in open(COVER) if line.strip()]
    have = {r["ts"][:13] for r in rows}
    t0 = rows[0]["ts"] if rows else datetime.now().astimezone().isoformat(timespec="seconds")
    out = []
    for hh in sorted({r[0] for r in c.execute("select substr(created_at,1,13) from evidence")}):
        cut = hh.replace(" ", "T")
        if hh.replace(" ", "T") in have or cut + ":59:59+11:00" >= t0:
            continue
        m = {}
        n = {k: 0 for k in METRICS if k.startswith("pairs_")}
        n["single_cell_pairs"] = 0
        for kind, ref, no in c.execute("select kind, source_ref, n_objects from evidence where created_at<=?", (hh + ":59:59",)):
            if kind != "specimen-pair":
                continue
            n["pairs_total"] += 1
            n["pairs_" + bucket(ref)] += 1
            n["single_cell_pairs"] += no == 1
        m.update(n)
        past = [r for r in cov if r["ts"][:19] <= cut + ":59:59"]
        if past:
            for k in ("verified", "evidence", "unknown"):
                m["die_" + k] = past[-1][k]
        out.append(dict(ts=cut + ":59:59+11:00", commit="backfill", m=m, backfill=True))
    return out


def commit():
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def main():
    rows = [json.loads(line) for line in open(LEDGER) if line.strip()] if LEDGER.exists() else []
    if "--backfill" in sys.argv:
        new = backfill(rows)
        rows = sorted(rows + new, key=lambda r: r["ts"])
        with open(LEDGER, "w") as f:
            f.writelines(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)
        log(f"backfilled {len(new)} hourly rows")
        return
    row = dict(ts=datetime.now().astimezone().isoformat(timespec="seconds"), commit=commit(), m=measure())
    if "--no-record" not in sys.argv:
        with open(LEDGER, "a") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    rows.append(row)
    prev = rows[-2] if len(rows) > 1 else None
    for k, (label, _) in METRICS.items():
        d = row["m"][k] - (prev["m"].get(k, row["m"][k]) if prev else row["m"][k])
        log(f"{label:45s} {row['m'][k]:>12,} {d:+,}")
    subprocess.run([sys.executable, str(REPO / "scripts/coverage_page_build.py"), str(OUT)], check=True)
    log(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
