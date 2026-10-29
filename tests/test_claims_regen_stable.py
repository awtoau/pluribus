"""Class tiers are computed from evidence rows, so wiping + re-registering the derived tables cannot move a class.

PREDICTION: rebuild (wipe, re-register claim + pattern + evidence links) twice -> class_verdict identical to the
pre-rebuild value; refuted by any tier/n/misses change.   python3 -m pytest tests/test_claims_regen_stable.py -v
"""
import os
import sys

import pytest
from sqlalchemy import insert, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
FAM, DEV = "cycloneiv", "EP4CGX150"
AXES = {"x": [1, 9], "y": [1, 9]}
SCOPES = [(1, 1), (9, 9), (1, 9), (9, 1), (5, 5)]      # corners (axis extremes) + interior = sampling bar for a 2-D law


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("PLURIBUS_DB_BACKEND", "sqlite")
    monkeypatch.setenv("PLURIBUS_SQLITE_PATH", str(tmp_path / "t.db"))
    import db
    db.BACKEND, db._SQPATH, db._engine = "sqlite", str(tmp_path / "t.db"), None
    import schema
    schema.init()
    from provenance import evidence_io as E
    with db.engine().begin() as c:
        E.ensure_family(c, FAM)
        yield c


def _register(conn, eids):
    """What claims_register does per class: claim WITH pattern + evidence links; no tier decided here."""
    import claims_register as CR
    R = CR.Reg(conn, FAM, DEV, "t")
    R.matcher("m-v1", "deterministic", "synthetic", 1, "x:y")
    pat = R.pattern("p-v1", "bit", "synthetic law", {"dims": 2, "axes": AXES}, matcher_id="m-v1")
    sid = R.scope("bit", "keys", {"keys": ["CLASS:S"]}, label="class S", n=1)
    c = R.claim("bit", "CLASS:S", sid, {"class": "S"}, "pattern-predicted", "open", pattern=pat, cls="S", n=1)
    for e in eids:
        conn.execute(insert(CR.S.claim_evidence).values(claim_id=c, evidence_id=e, role="confirm"))


def test_regeneration_keeps_class_verdict(conn):
    import claims_register as CR
    from provenance import evidence_io as E, tiering
    eids = [E.record_decode(conn, FAM, DEV, f"e{i}", {"meta": {"tile": list(t)}}, "t", "test", kind="specimen-pair")
            for i, t in enumerate(SCOPES)]
    _register(conn, eids)
    before = tiering.class_verdict(conn, FAM, DEV, "S")
    assert before["tier"] == "sampled" and before["n"] == 5
    for _ in range(2):
        CR.wipe(conn, FAM)                                  # evidence survives, claims/patterns do not
        assert conn.execute(select(CR.S.claims.c.id)).fetchone() is None
        _register(conn, eids)
        assert tiering.class_verdict(conn, FAM, DEV, "S") == before


def test_regeneration_keeps_gate_runs(conn):
    """A gate run is a vendor-oracle record: the claims rebuild must never wipe it."""
    import claims_register as CR
    from provenance import corpus as C
    C.ensure_member(conn, FAM, "m1", "oracle-build", "t", device=DEV)
    rid = C.record_gate_run(conn, FAM, "synthetic", "t",
                            {"m1": {"pips": {"matched": 3, "missing": 2, "extra": 0, "wrong": 1}}},
                            params={"flag": "off"})
    for _ in range(2):
        CR.wipe(conn, FAM)
        C.ensure_member(conn, FAM, "m1", "oracle-build", "t", device=DEV)
    assert conn.execute(select(CR.S.gate_runs.c.id)).scalars().all() == [rid]
    r = conn.execute(select(CR.S.gate_results)).fetchall()
    assert len(r) == 1 and (r[0].matched, r[0].missing, r[0].wrong) == (3, 2, 1)
