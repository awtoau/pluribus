"""Read-side bridge for scripts that consumed evidence JSON files: same dict shapes, from the family DB.

  specimen_table(family, device, source_ref) -> {pair: {<meta...>, "on": [flat], "off": [flat]}} | None
  ledger_tiers(family, device, commit, classes) -> {class: {"<tier>/<status>": n_objects}} (claims + unknowns)

None / {} when the DB has no provenance rows (caller falls back or records nothing).
"""
import sys
from pathlib import Path

from sqlalchemy import and_, insert, select

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import db                                   # noqa: E402
import schema as S                          # noqa: E402
from provenance import evidence_io as E     # noqa: E402
from provenance import queries as Q         # noqa: E402


def _has_tables(conn):
    return conn.dialect.has_table(conn, "evidence")


def specimen_table(family, device, source_ref):
    with db.engine().connect() as conn:
        if not _has_tables(conn):
            return None
        rows = conn.execute(select(S.evidence.c.name, S.evidence.c.result, S.evidence.c.bits_spec, S.evidence.c.bits_base).where(and_(
            S.evidence.c.family == family, S.evidence.c.device == device, S.evidence.c.kind == "specimen-pair",
            S.evidence.c.source_ref == source_ref))).fetchall()
    if not rows:
        return None
    out = {}
    for name, result, spec, base in rows:
        rec = dict(result.get("meta") or {})
        rec["on"] = E.unpack(spec).tolist()
        rec["off"] = E.unpack(base).tolist()
        if result.get("base") is not None:
            rec["base"] = result["base"]
        out[name] = rec
    return out


def ledger_tiers(family, device, commit, classes):
    """Per inventory class: {tier/status: n_objects} from claims + unknowns. Also appends coverage_ledger
    rows (source inventory-live) carrying the live partition totals per class."""
    import datetime
    with db.engine().begin() as conn:
        if not _has_tables(conn):
            return {}
        cov = Q.coverage(conn, family, device)
        if not cov:
            return {}
        out = {}
        for (cls, tier, status), n in cov.items():
            out.setdefault(cls, {})[f"{tier}/{status}"] = n
        ts = datetime.datetime.now().astimezone()
        conn.execute(insert(S.coverage_ledger), [dict(family=family, device=device, commit=commit, ts=ts, inventory_class=cid,
                                                     tier="partition", status="live", n_objects=int(total), denominator="die_bits",
                                                     source="inventory-live") for cid, total in classes])
    return out
