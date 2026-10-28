"""Read-side bridge for scripts that consumed evidence JSON files: same dict shapes, from the family DB.

  specimen_table(family, device, source_ref) -> {pair: {<meta...>, "on": [flat], "off": [flat]}} | None
  ledger_tiers(family, device, commit, classes) -> {class: {"<tier>/<status>": n_objects}} (claims + unknowns)

The family database is dbtools.family_db(family): $PLURIBUS_SQLITE_PATH when set, else
databases/<family>/<default>. Reads are direct read-only sqlite3 connections (no schema.init, no engine
singleton), so a pipeline pointed at another file can still consult the family's evidence.
None / {} when the file or the rows are absent (caller falls back or records nothing).
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import dbtools                              # noqa: E402
from provenance import evidence_io as E     # noqa: E402

TIER_SQL = ("SELECT inventory_class, tier, status, SUM(n_objects) FROM claims WHERE family=? AND device=? "
            "GROUP BY inventory_class, tier, status")
UNK_SQL = "SELECT inventory_class, status, SUM(n_objects) FROM unknowns WHERE family=? AND device=? GROUP BY inventory_class, status"


def _open(family):
    path = dbtools.family_db(family)
    if not os.path.exists(path):
        return None, path
    conn = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
    has = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='evidence'").fetchone()
    if not has:
        conn.close()
        return None, path
    return conn, path


def specimen_table(family, device, source_ref):
    conn, _path = _open(family)
    if conn is None:
        return None
    try:
        rows = conn.execute("SELECT name, result, bits_spec, bits_base FROM evidence WHERE family=? AND device=? "
                            "AND kind='specimen-pair' AND source_ref=?", (family, device, source_ref)).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    out = {}
    for name, result, spec, base in rows:
        result = json.loads(result) if isinstance(result, str) else result
        rec = dict(result.get("meta") or {})
        rec["on"] = E.unpack(spec).tolist()
        rec["off"] = E.unpack(base).tolist()
        if result.get("base") is not None:
            rec["base"] = result["base"]
        out[name] = rec
    return out


def ledger_tiers(family, device, commit, classes):
    """Per inventory class: {tier/status: n_objects} from claims + unknowns (read-only; the ledger line
    carries it). coverage_ledger rows for the live partition are written by claims_register, not here."""
    conn, _path = _open(family)
    if conn is None:
        return {}
    try:
        out = {}
        for cls, tier, status, n in conn.execute(TIER_SQL, (family, device)):
            out.setdefault(cls or "-", {})[f"{tier}/{status}"] = int(n or 0)
        for cls, status, n in conn.execute(UNK_SQL, (family, device)):
            out.setdefault(cls or "-", {})[f"unknown/{status}"] = out.get(cls or "-", {}).get(f"unknown/{status}", 0) + int(n or 0)
    finally:
        conn.close()
    return out
