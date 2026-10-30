"""Coverage tier is computed from claims/evidence (provenance/tiering.py): adding rows moves a class between tiers.

  python3 -m pytest tests/test_tiering.py -v
"""
import datetime
import os
import sys

import pytest
from sqlalchemy import insert

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
FAM, DEV = "cycloneiv", "EP4CGX150"


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


def _claim(c, cid, tier, law=None):
    import schema as S
    if law is not None:
        c.execute(insert(S.claim_patterns).values(id=f"p-{cid}", family=FAM, device=DEV, space="bit", description="t", law=law,
                                                  status="open", created_commit="t"))
    sid = c.execute(insert(S.scopes).values(family=FAM, device=DEV, space="bit", kind="keys", definition={"keys": [cid]},
                                            scope_key=f"k-{cid}", n_objects=1)).inserted_primary_key[0]
    return c.execute(insert(S.claims).values(
        family=FAM, device=DEV, space="bit", subject_key=f"CLASS:{cid}", scope_id=sid, meaning={}, tier=tier, status="open",
        pattern_id=f"p-{cid}" if law is not None else None, n_objects=1, inventory_class=cid, created_commit="t",
        updated_at=datetime.datetime.now().astimezone())).inserted_primary_key[0]


def _link(c, claim, role, name, kind="specimen-pair", tile=None, group=None):
    import schema as S
    from provenance import evidence_io as E
    res = {"meta": {"tile": list(tile)}} if tile else {}
    if group is not None:
        res["meta"]["group_key"] = group
    eid = E.record_decode(c, FAM, DEV, name, res, "t", "test", kind=kind)
    c.execute(insert(S.claim_evidence).values(claim_id=claim, evidence_id=eid, role=role))


def test_pattern_needs_five_scopes_with_extremes_then_refutation_flips_it(conn):
    from provenance import tiering
    claim = _claim(conn, "T", "pattern-predicted", {"dims": 2, "axes": {"x": [1, 9], "y": [1, 9]}})
    for i, t in enumerate([(1, 1), (9, 9), (5, 5), (3, 7)]):
        _link(conn, claim, "confirm", f"e{i}", tile=t)
    v = tiering.class_verdict(conn, FAM, DEV, "T")
    assert v["tier"] == "predicted" and v["n"] == 4                      # 4 scopes < 5 for a 2-D law
    _link(conn, claim, "confirm", "e4", tile=(2, 2))
    v = tiering.class_verdict(conn, FAM, DEV, "T")
    assert v["tier"] == "sampled" and v["n"] == 5 and v["misses"] == 0   # 5 scopes, extremes 1 and 9 on both axes
    _link(conn, claim, "refute", "bad", tile=(4, 4))
    v = tiering.class_verdict(conn, FAM, DEV, "T")
    assert v["tier"] == "refuted" and v["misses"] == 1                   # one refuting row flips the class


def test_extremes_are_required(conn):
    from provenance import tiering
    claim = _claim(conn, "E", "pattern-predicted", {"dims": 2, "axes": {"x": [1, 9], "y": [1, 9]}})
    for i, t in enumerate([(2, 2), (3, 3), (4, 4), (5, 5), (6, 6)]):
        _link(conn, claim, "confirm", f"e{i}", tile=t)
    v = tiering.class_verdict(conn, FAM, DEV, "E")
    assert v["tier"] == "predicted" and "extremes missing" in v["rule"]


def test_conflict_makes_suspect_and_exact_rows_make_measured(conn):
    from provenance import tiering
    c1 = _claim(conn, "S", "pattern-predicted", {"dims": 1})
    _link(conn, c1, "confirm", "s0", tile=(1, 1))
    assert tiering.class_verdict(conn, FAM, DEV, "S")["tier"] == "predicted"
    _link(conn, c1, "conflict", "s-bad", kind="audit")
    assert tiering.class_verdict(conn, FAM, DEV, "S")["tier"] == "suspect"
    c2 = _claim(conn, "M", "measured")
    assert tiering.class_verdict(conn, FAM, DEV, "M")["tier"] == "unknown"      # measured needs exact rows
    _link(conn, c2, "direct", "m0")
    assert tiering.class_verdict(conn, FAM, DEV, "M")["tier"] == "measured"
    c3 = _claim(conn, "V", "pattern-predicted", {"dims": 2})
    _link(conn, c3, "direct", "o0", kind="oracle-compare")
    assert tiering.class_verdict(conn, FAM, DEV, "V")["tier"] == "verified"
    _claim(conn, "D", "vendor-decoded")
    assert tiering.class_verdict(conn, FAM, DEV, "D")["tier"] == "decoded"
    assert tiering.class_verdict(conn, FAM, DEV, "none")["tier"] == "unknown"


def test_sampling_bar_single_rule():
    from provenance import tiering
    two_d = {"dims": 2, "axes": {"x": [1, 9], "y": [1, 9]}}
    pts = {(1, 1), (9, 9), (5, 5), (3, 7), (2, 2)}
    assert tiering.sampling_bar(two_d, pts)[0]
    assert not tiering.sampling_bar(two_d, pts - {(2, 2)})[0]                 # 4 < 5
    assert not tiering.sampling_bar(two_d, {(2, 2), (3, 3), (4, 4), (5, 5), (6, 6)})[0]   # extremes missing
    ok, need, dims, why = tiering.sampling_bar({"dims": 2}, pts)              # 2-D without axes never passes
    assert not ok and dims == 2 and "no axes" in why
    assert not tiering.sampling_bar({}, pts)[0]                               # default dims is 2 (as class_verdict)
    assert tiering.sampling_bar({"dims": 1}, {(1, 1), (2, 1), (3, 1)})[0]


def test_feedback_graduates_by_tiering_rule(conn):
    import schema as S
    from provenance import feedback as F, scopes as SC
    law = {"dims": 2}                                                          # no axes -> must NOT graduate
    conn.execute(insert(S.claim_patterns).values(id="pg", family=FAM, device=DEV, space="bit", description="t", law=law,
                                                 status="open", created_commit="t"))
    for i in range(6):
        d = {"x": i, "y": i, "offsets": [[0, 0]]}
        sid = conn.execute(insert(S.scopes).values(family=FAM, device=DEV, space="bit", kind="tile", definition=d,
                                                   scope_key=SC.canonical("bit", "tile", d), n_objects=1)).inserted_primary_key[0]
        F.event(conn, "confirmed", "t", pattern_id="pg", detail={"scope_id": sid})
    F._graduate(conn, "pg", "t")
    assert F._pattern(conn, "pg")["status"] == "open"
    conn.execute(S.claim_patterns.update().where(S.claim_patterns.c.id == "pg").values(law={"dims": 2, "axes": {"x": [0, 5], "y": [0, 5]}}))
    F._graduate(conn, "pg", "t")
    assert F._pattern(conn, "pg")["status"] == "verified-by-sampling"


def test_statistical_is_its_own_tier(conn):
    from provenance import tiering
    _claim(conn, "ST", "statistical")
    assert tiering.class_verdict(conn, FAM, DEV, "ST")["tier"] == "statistical"
    assert "statistical" in tiering.TIERS_OUT


def test_build_id_registers_from_design_toml(conn):
    from provenance import corpus
    import glob
    import os
    import pytest
    d = sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus", "cycloneiv", "gxbh_*", "design.toml")))
    if not d:
        pytest.skip("no kept gxbh_* design with a design.toml in corpus/cycloneiv (corpus pruned, reference/corpus_keep.tsv)")
    name = os.path.basename(os.path.dirname(d[0]))
    a = corpus.build_id(conn, FAM, name)
    assert a == corpus.build_id(conn, FAM, name)        # idempotent on the dir name


def test_constant_per_group_law_ignores_single_row_groups(conn):
    from provenance import tiering
    claim = _claim(conn, "G", "pattern-predicted", {"dims": 2, "axes": {"x": [1, 9], "y": [1, 9]}, "min_rows_per_group": 2})
    for i, t in enumerate([(1, 1), (9, 9), (5, 5), (3, 7), (2, 2), (4, 4), (6, 6)]):   # 7 single-row groups
        _link(conn, claim, "parent", f"s{i}", tile=t, group=f"g{i}")
    v = tiering.class_verdict(conn, FAM, DEV, "G")
    assert v["tier"] == "predicted" and v["n"] == 0                      # single rows are not constancy evidence
    for i, t in enumerate([(1, 1), (9, 9), (5, 5), (3, 7), (2, 2)]):     # a second row in 5 groups
        _link(conn, claim, "confirm", f"c{i}", tile=t, group=f"g{i}")
    v = tiering.class_verdict(conn, FAM, DEV, "G")
    assert v["tier"] == "sampled" and v["n"] == 5
