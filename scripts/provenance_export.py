#!/usr/bin/env python3.15t
"""Deterministic text export of the provenance tables, tracked in git (reviewable, recoverable).

  python3.15t scripts/provenance_export.py --family cycloneiv            # DB -> provenance-export/<family>/*.tsv
  python3.15t scripts/provenance_export.py --family cycloneiv --check    # load(export(db)) == db (temp DB)
  python3.15t scripts/provenance_export.py --family cycloneiv --import DIR --into PATH   # rebuild a DB from an export

Natural keys only (no autoincrement ids): evidence (device, kind, name, source_ref), scopes
(device, scope_key), claims (device, space, subject_key, scope_key), patterns (id), ... Rows sorted by
key; JSON columns canonical; bit sets as base64 of the delta-varint BLOB (one encoding, one hash).
Kept DBs are gitignored, so this is the durable copy of the small tables; the big lift tables are not
exported (regenerable from bitstreams). Log: tmp/logs/provenance_export.log
"""
import argparse
import base64
import datetime
import hashlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import and_, create_engine, insert, select

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import db                                   # noqa: E402
import schema as S                          # noqa: E402
from provenance import scopes as SC         # noqa: E402

log = logging.getLogger("provenance_export")
OUT = REPO / "provenance-export"

# table -> (natural key columns, columns to export, foreign refs {col: (table, natural-key-cols-of-target)})
SPEC = {
    "families":        (("id",), None, {}),
    "devices":         (("family", "name"), None, {}),
    "address_spaces":  (("family", "space"), None, {}),
    "matchers":        (("id",), None, {}),
    "scopes":          (("family", "device", "scope_key"), None, {"parent": ("scopes", ("family", "device", "scope_key"))}),
    "evidence":        (("family", "device", "kind", "name", "source_ref"), None, {}),
    "evidence_scopes": (("evidence_id", "scope_id"), None, {"evidence_id": ("evidence", None), "scope_id": ("scopes", None)}),
    "claim_patterns":  (("id",), None, {"scope_id": ("scopes", None)}),
    "pattern_evidence": (("pattern_id", "evidence_id", "role"), None, {"evidence_id": ("evidence", None)}),
    "claims":          (("family", "device", "space", "subject_key", "scope_id"), None,
                        {"scope_id": ("scopes", None), "superseded_by": ("claims", None)}),
    "claim_evidence":  (("claim_id", "evidence_id", "role"), None, {"claim_id": ("claims", None), "evidence_id": ("evidence", None)}),
    "claim_conflicts": (("claim_a", "claim_b"), None, {"claim_a": ("claims", None), "claim_b": ("claims", None), "winner": ("claims", None)}),
    "expectations":    (("family", "device", "space", "subject_key", "scope_id", "matcher_id"), None,
                        {"scope_id": ("scopes", None), "resolved_evidence": ("evidence", None), "claim_id": ("claims", None)}),
    "unknowns":        (("family", "device", "space", "subject_key", "scope_id"), None,
                        {"scope_id": ("scopes", None), "absence_evidence": ("evidence", None)}),
    "audits":          (("family", "device", "scope_id", "pattern_id", "claim_id", "expectation_id", "reason", "queued_commit"), None,
                        {"scope_id": ("scopes", None), "claim_id": ("claims", None), "expectation_id": ("expectations", None),
                         "evidence_id": ("evidence", None)}),
    "claim_events":    (("ts", "event", "claim_id", "pattern_id", "expectation_id", "unknown_id", "evidence_id", "commit"), None,
                        {"claim_id": ("claims", None), "expectation_id": ("expectations", None), "unknown_id": ("unknowns", None),
                         "evidence_id": ("evidence", None)}),
    "corpus_members":  (("family", "name"), None, {}),
    "gate_runs":       (("family", "script", "commit", "ts"), None, {}),
    "gate_results":    (("run_id", "member_id", "category"), None, {"run_id": ("gate_runs", None), "member_id": ("corpus_members", None)}),
    "done_criteria":   (("family",), None, {"met_run": ("gate_runs", None)}),
    "coverage_ledger": (("family", "device", "commit", "ts", "inventory_class", "tier", "status", "denominator", "source"), None, {}),
}
ORDER = list(SPEC)
BLOB_COLS = {"bits_spec", "bits_base"}
SKIP_COLS = {"build_id", "build_base", "build_spec"}   # postfit_builds refs are per-DB; Integer `id` PKs skipped below


def _skip(col):
    # scopes.scope_key is canonical(space, kind, definition): recomputed on import, not exported twice
    return (col.name in SKIP_COLS or (col.name == "id" and col.type.__class__.__name__ == "Integer")
            or (col.table.name == "scopes" and col.name == "scope_key"))


def scope_digest(family, device, scope_key):
    """Short stable reference for a scope row (scope_key can be kilobytes)."""
    return hashlib.sha256(f"{family}\x1f{device}\x1f{scope_key}".encode()).hexdigest()[:16]


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        return "b64:" + base64.b64encode(v).decode()
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (dict, list)):
        return "json:" + json.dumps(v, sort_keys=True, separators=(",", ":"))
    if isinstance(v, datetime.datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, float):
        return repr(v)
    return str(v).replace("\t", "\\t").replace("\n", "\\n")


def _uncell(s, col):
    if s == "":
        return None
    if s.startswith("b64:"):
        return base64.b64decode(s[4:])
    if s.startswith("json:"):
        return json.loads(s[5:])
    t = col.type.__class__.__name__
    if t in ("Integer", "SmallInteger", "BigInteger"):
        return int(s)
    if t == "Float":
        return float(s)
    if t == "Boolean":
        return s == "1"
    if t == "DateTime":
        return datetime.datetime.fromisoformat(s)
    return s.replace("\\n", "\n").replace("\\t", "\t")


def _natkey_of(conn, table, row_id, cache):
    """id -> natural key tuple (as a '|'-joined string) for cross-row references."""
    k = (table, row_id)
    if k in cache:
        return cache[k]
    t = S.metadata.tables[table]
    keys = SPEC[table][0]
    r = conn.execute(select(*[t.c[c] for c in keys]).where(t.c.id == row_id)).fetchone()
    if r is None:
        db.die(f"{table}.id={row_id} referenced but absent")
    if table == "scopes":
        s = scope_digest(*r)
        cache[k] = s
        return s
    parts = []
    for c, v in zip(keys, r):
        if c.endswith("_id") or c in ("claim_a", "claim_b", "parent", "run_id", "member_id"):
            ref = SPEC[table][2].get(c)
            parts.append(_natkey_of(conn, ref[0], v, cache) if (ref and v is not None) else _cell(v))
        else:
            parts.append(_cell(v))
    s = "\x1f".join(parts)
    cache[k] = s
    return s


def export(conn, family, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = {}
    sizes = {}
    for name in ORDER:
        t = S.metadata.tables[name]
        keys, _cols, refs = SPEC[name]
        cols = [c.name for c in t.columns if not _skip(c)]
        stmt = select(t)
        if "family" in t.c:
            stmt = stmt.where(t.c.family == family)
        rows = []
        for r in conn.execute(stmt):
            r = dict(r._mapping)
            rec = {}
            for c in cols:
                v = r[c]
                if c in refs and v is not None:
                    v = "ref:" + _natkey_of(conn, refs[c][0], v, cache)
                    rec[c] = v
                else:
                    rec[c] = _cell(v)
            if name == "scopes":
                if r["scope_key"] != SC.canonical(r["space"], r["kind"], r["definition"]):
                    db.die(f"scopes.id={r['id']} has a non-canonical scope_key; the export cannot reproduce it")
                rec["_sort"] = (scope_digest(r["family"], r["device"], r["scope_key"]),)
            else:
                rec["_sort"] = tuple(("ref:" + _natkey_of(conn, refs[c][0], r[c], cache)) if (c in refs and r[c] is not None)
                                     else _cell(r[c]) for c in keys)
            rows.append(rec)
        rows.sort(key=lambda x: x["_sort"])
        lines = ["\t".join(cols)]
        for rec in rows:
            lines.append("\t".join(rec[c] for c in cols))
        text = "\n".join(lines) + "\n"
        (out_dir / f"{name}.tsv").write_text(text)
        sizes[name] = (len(rows), len(text))
    total = sum(s for _, s in sizes.values())
    with open(out_dir / "MANIFEST.tsv", "w") as fh:
        fh.write("table\trows\tbytes\tsha256\n")
        for name in ORDER:
            h = hashlib.sha256((out_dir / f"{name}.tsv").read_bytes()).hexdigest()
            fh.write(f"{name}\t{sizes[name][0]}\t{sizes[name][1]}\t{h}\n")
    log.info("exported %s: %d tables, %d rows, %.1f KB -> %s", family, len(sizes), sum(n for n, _ in sizes.values()),
             total / 1024, out_dir)
    return sizes


def _resolve(conn, table, natkey, cache):
    """natural key string -> id in the target DB."""
    k = (table, natkey)
    if k in cache:
        return cache[k]
    t = S.metadata.tables[table]
    keys = SPEC[table][0]
    if table == "scopes":
        if ("scopes", "*") not in cache:
            cache[("scopes", "*")] = True
            for r in conn.execute(select(t.c.id, t.c.family, t.c.device, t.c.scope_key)):
                cache[("scopes", scope_digest(r[1], r[2], r[3]))] = r[0]
        if k not in cache:
            db.die(f"import: scope {natkey} not found")
        return cache[k]
    parts = natkey.split("\x1f")
    conds = []
    for c, p in zip(keys, parts):
        ref = SPEC[table][2].get(c)
        if ref and p != "":
            conds.append(t.c[c] == _resolve(conn, ref[0], p, cache))
        elif p == "":
            conds.append(t.c[c].is_(None))
        else:
            conds.append(t.c[c] == _uncell(p, t.c[c]))
    r = conn.execute(select(t.c.id).where(and_(*conds))).fetchone()
    if r is None:
        db.die(f"import: {table} row {natkey!r} not found while resolving a reference")
    cache[k] = r[0]
    return r[0]


def import_dir(conn, in_dir):
    cache = {}
    counts = {}
    for name in ORDER:
        p = in_dir / f"{name}.tsv"
        if not p.exists():
            continue
        t = S.metadata.tables[name]
        refs = SPEC[name][2]
        lines = p.read_text().splitlines()
        cols = lines[0].split("\t")
        if name == "scopes":
            # parents before children (file order is by digest); each inserted row feeds the digest map directly
            cache[("scopes", "*")] = True
            pending = []
            for ln in lines[1:]:
                vals = dict(zip(cols, ln.split("\t")))
                pending.append(vals)
            while pending:
                rest = []
                for vals in pending:
                    par = vals.get("parent", "")
                    if par and ("scopes", par[4:]) not in cache:
                        rest.append(vals)
                        continue
                    rec = {c: (cache[("scopes", v[4:])] if v.startswith("ref:") else _uncell(v, t.c[c])) for c, v in vals.items()}
                    rec["scope_key"] = SC.canonical(rec["space"], rec["kind"], rec["definition"])
                    rid = conn.execute(insert(t).values(**rec)).inserted_primary_key[0]
                    cache[("scopes", scope_digest(rec["family"], rec["device"], rec["scope_key"]))] = rid
                if len(rest) == len(pending):
                    db.die(f"import: {len(rest)} scopes reference parents that do not exist")
                pending = rest
            counts[name] = len(lines) - 1
            continue
        rows = []
        for ln in lines[1:]:
            vals = ln.split("\t")
            rec = {}
            for c, v in zip(cols, vals):
                if v.startswith("ref:"):
                    rec[c] = _resolve(conn, refs[c][0], v[4:], cache)
                else:
                    rec[c] = _uncell(v, t.c[c])
            rows.append(rec)
        for rec in rows:   # one by one: self-references (claims.superseded_by) need prior rows
            conn.execute(insert(t).values(**rec))
        counts[name] = len(rows)
    return counts


def check(family, out_dir):
    """load(export(db)) == db: export live, import into a temp DB, export again, compare bytes."""
    live = Path(tempfile.mkdtemp(prefix="prov_live_", dir=REPO / "tmp"))
    again = Path(tempfile.mkdtemp(prefix="prov_again_", dir=REPO / "tmp"))
    with db.engine().connect() as conn:
        export(conn, family, live)
    tmp_db = REPO / "tmp" / f"prov_check_{family}.db"
    if tmp_db.exists():
        tmp_db.unlink()
    eng = create_engine(f"sqlite:///{tmp_db}")
    S.metadata.create_all(eng)
    with eng.begin() as conn:
        counts = import_dir(conn, live)
    with eng.connect() as conn:
        export(conn, family, again)
    bad = []
    for name in ORDER:
        a, b = (live / f"{name}.tsv").read_bytes(), (again / f"{name}.tsv").read_bytes()
        if a != b:
            bad.append(name)
    log.info("check %s: %d rows reimported; %s", family, sum(counts.values()),
             "IDENTICAL after round trip" if not bad else f"DIFFER: {bad}")
    return not bad


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/provenance_export.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--import", dest="imp", default=None, help="import this export dir into --into (fresh DB)")
    ap.add_argument("--into", default=None)
    a = ap.parse_args()
    out = Path(a.out) if a.out else OUT / a.family
    if a.imp:
        if not a.into:
            ap.error("--import needs --into PATH")
        eng = create_engine(f"sqlite:///{a.into}")
        S.metadata.create_all(eng)
        with eng.begin() as conn:
            c = import_dir(conn, Path(a.imp))
        log.info("imported %s", c)
        return 0
    if a.check:
        return 0 if check(a.family, out) else 1
    S.init()
    with db.engine().connect() as conn:
        export(conn, a.family, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
