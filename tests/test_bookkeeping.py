"""Bookkeeping enforcement (recovery-process.md): unbuilt specimen rows rejected, yield vs floor, gate exit code,
failed/refused builds stored. Temp SQLite, no builds."""
import contextlib
import datetime
import os
import sqlite3
import sys

import pytest
from sqlalchemy import insert, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
COMMIT = "deadbeef"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    p = str(tmp_path / "bk.db")
    monkeypatch.setenv("PLURIBUS_DB_BACKEND", "sqlite")
    monkeypatch.setenv("PLURIBUS_SQLITE_PATH", p)
    import db
    db.BACKEND, db._SQPATH, db._engine = "sqlite", p, None
    import schema
    schema.init()
    yield p
    db._engine = None


def spec(conn, name, ref="bit_hunter:A", **kw):
    from provenance import evidence_io as E
    return E.record_specimen(conn, "cycloneiv", "EP4CGX150", name, "b", [[1, 5]], [], {}, ref, "g.py", COMMIT, 100, **kw)


def test_unbuilt_specimen_rejected_and_audited():
    import db
    from provenance import corpus as C
    from provenance import evidence_io as E
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        with pytest.raises(SystemExit):
            spec(conn, "p0")
        with pytest.raises(SystemExit):
            spec(conn, "p1", build_base=C.record_build_outcome(conn, "cycloneiv", "d", "bA", "ok", ""))
        a = C.record_build_outcome(conn, "cycloneiv", "d", "bA", "ok", "")
        b = C.record_build_outcome(conn, "cycloneiv", "d", "bB", "ok", "")
        spec(conn, "p2", build_base=a, build_spec=b)
        spec(conn, "legacy", ref="evidence/old/x.json", allow_unbuilt=True)
        assert E.audit_unbuilt(conn, "cycloneiv") == {"g.py :: bit_hunter": (0, 1), "g.py :: evidence/old": (1, 1)}


def test_other_family_not_enforced():
    import db
    from provenance import evidence_io as E
    with db.engine().begin() as conn:
        E.ensure_family(conn, "ecp5")
        E.record_specimen(conn, "ecp5", "d", "p", "b", [[1, 5]], [], {}, "r", "g", COMMIT, 100)


def test_gate_exit_code():
    from provenance import corpus as C
    assert C.gate_exit_code(7, "x.py") == 0
    assert C.gate_exit_code(None, "x.py") == 4


def test_build_outcome_stored_and_updated():
    import db
    import schema as S
    from provenance import corpus as C
    with db.engine().begin() as conn:
        i = C.record_build_outcome(conn, "cycloneiv", "d", "dz", "refused", "disk floor")
        assert C.record_build_outcome(conn, "cycloneiv", "d", "dz", "failed", "fit error") == i
        assert conn.execute(select(S.corpus_builds.c.status)).scalar() == "failed:fit error"
        with pytest.raises(SystemExit):
            C.record_build_outcome(conn, "cycloneiv", "d", "dy", "failed", "")


def test_pool_reports_failed_builds(monkeypatch):
    import build_pool as bp
    monkeypatch.setattr(bp.heavy_guard, "lease", lambda *a, **k: contextlib.nullcontext())
    got = []

    def fn(x):
        if x == 1:
            raise RuntimeError("quartus died")
        return bp.BuildOutcome("refused", "no ram") if x == 2 else x
    res = bp.map_adaptive(fn, [0, 1, 2], max_workers=2, on_outcome=lambda it, o: got.append((it, o.status, o.reason)))
    assert res[0] == 0 and sorted(got) == [(1, "failed", "RuntimeError: quartus died"), (2, "refused", "no ram")]


def test_yield_new_features_only(fresh_db):
    import progress_ledger as P
    c = sqlite3.connect(fresh_db)
    t = datetime.datetime.now().astimezone()
    prev = (t - datetime.timedelta(hours=1)).isoformat()
    old = (t - datetime.timedelta(hours=2)).replace(tzinfo=None).isoformat(sep=" ")
    new = t.replace(tzinfo=None).isoformat(sep=" ")
    c.execute("insert into families(id,vendor,name,lut_inputs,bit_model) values('cycloneiv','v','n',4,'m')")

    def ev(i, name, ref, ts, bb=None, bs=None):
        c.execute("insert into evidence(id,kind,family,device,name,source_ref,generator,build_base,build_spec,result,n_objects,\"commit\",created_at)"
                  " values(?, 'specimen-pair','cycloneiv','d',?,?, 'g', ?, ?, '{}', 1, 'c', ?)", (i, name, ref, bb, bs, ts))

    def claim(i, status, evs):
        c.execute("insert into claims(id,family,device,space,subject_key,scope_id,meaning,tier,status,created_commit)"
                  " values(?, 'cycloneiv','d','bit',?,1,'{}','measured',?, 'c')", (i, f"k{i}", status))
        for e in evs:
            c.execute("insert into claim_evidence(claim_id,evidence_id,role) values(?,?,'direct')", (i, e))
    ev(1, "old", "bit_hunter:A", old)
    ev(2, "n1", "bit_hunter:A", new, 10, 11)
    ev(3, "n2", "bit_hunter:A", new, 10, 12)
    ev(4, "n3_null_seed", "bit_hunter:A", new, 13, 14)       # calibration: 0 builds, 0 features
    claim(1, "confirmed", [1, 2])    # re-measure of an old cell: 0
    claim(2, "confirmed", [2])       # new feature
    claim(3, "open", [3])            # not answered: 0
    claim(4, "confirmed", [3, 4])    # new feature
    c.commit()
    y = P.compute_yield(c, prev)["bit hunter"]
    assert (y["builds"], y["features"]) == (3, 2) and y["floor"] == 1 and not y["below"]
    assert y["yield_"] == pytest.approx(200 / 3)
    assert P.compute_yield(c, None) == {}
    P.FLOOR["bit hunter"] = 100
    assert P.compute_yield(c, prev)["bit hunter"]["below"]
