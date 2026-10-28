#!/usr/bin/env python3.15t
"""Content-level comparison of SQLite databases (per-table row counts + order-independent content hash).

  python3.15t scripts/db_content_compare.py --ref databases/aw2.db databases/aw2_verify.db [more.db ...]

Byte-level sha256 of a SQLite file is not identity: page layout, freelist and an un-checkpointed -wal
differ between files with the same rows. This opens every file read-only, lists its tables, and for
each table hashes `SELECT * ORDER BY <all columns>` (sha256 over the repr of each row). Prints a table
per database: identical / differing tables; exit 0 iff every candidate matches the reference exactly
(same table set, same counts, same hashes). Log: tmp/logs/db_content_compare.log
"""
import argparse
import hashlib
import json
import logging
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
log = logging.getLogger("db_content_compare")


def table_hashes(path):
    conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    out = {}
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for t in tables:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
        order = ", ".join(f'"{c}"' for c in cols if c != "id") or '"id"'   # ids are allocation order, not content
        sel = ", ".join(f'"{c}"' for c in cols if c != "id") or '"id"'
        h = hashlib.sha256()
        n = 0
        for row in conn.execute(f'SELECT {sel} FROM "{t}" ORDER BY {order}'):
            h.update(repr(row).encode())
            h.update(b"\n")
            n += 1
        out[t] = (n, h.hexdigest()[:16])
        log.info("%s %-24s %9d rows %s", Path(path).name, t, n, out[t][1])
    conn.close()
    return out


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/db_content_compare.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True)
    ap.add_argument("candidates", nargs="+")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    ref = table_hashes(a.ref)
    result = {}
    all_ok = True
    for c in a.candidates:
        cand = table_hashes(c)
        diff = {}
        for t in sorted(set(ref) | set(cand)):
            if ref.get(t) != cand.get(t):
                diff[t] = {"ref": ref.get(t), "cand": cand.get(t)}
        result[c] = {"identical": not diff, "differing": diff, "tables": len(cand)}
        all_ok &= not diff
        print(f"{Path(c).name}: {'CONTENT-IDENTICAL to ' + Path(a.ref).name if not diff else str(len(diff)) + ' differing tables: ' + ', '.join(sorted(diff))}")
        for t, d in sorted(diff.items()):
            print(f"   {t:24s} ref {d['ref']}  cand {d['cand']}")
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
