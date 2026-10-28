"""Pattern matchers (scripts/pattern_matchers.py): propose / predict / verify; expectations only."""
import os
import sys

import pytest
from sqlalchemy import insert, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

COMMIT = "deadbeef"


def law(w):
    return [1111 + (w >> 5), 2805 - 2 * (w & 15) - 2 * ((w >> 3) & 1) - ((w >> 4) & 1)]


def test_bit_linear_recovers_the_m9k_x1_law_and_verifies_held_out():
    import pattern_matchers as PM
    m = {str(w): law(w) for w in range(0, 9216, 7)}
    mt = PM.BitLinearLaw()
    c = mt.propose({"subject": "M9K:init:w1", "index_to_cell": m, "parents": [1],
                    "scope": {"space": "cell-param", "kind": "keys", "definition": {"keys": ["M9K:init:w1"]}}})[0]
    assert c.fit["hits"] == c.fit["total"]
    assert c.law["frame"][:1] == [1111] and c.law["v"][0] == 2805
    res = PM.verify_all(mt, c, {w: law(w) for w in range(1, 9216, 11)})
    assert res["refuted"] == 0 and res["confirmed"] > 800
    assert mt.verify(c, 5, [0, 0]) == "refuted"
    assert c.confidence == 1.0


def test_tile_translate_needs_agreement():
    import pattern_matchers as PM
    mt = PM.TileClassTranslate(min_positions=2)
    tiles = {(10, 10): {"0,2": [[0, 1], [3, -4]]}, (58, 30): {"0,2": [[0, 1], [3, -4]]}, (37, 60): {"0,2": [[0, 1], [9, 9]]}}
    cs = mt.propose({"tiles": tiles, "parents": {(10, 10): [1], (58, 30): [2], (37, 60): [3]}, "subject": "LOCAL_LINE:{key}",
                     "class_scope": {"space": "bit", "kind": "tile-class", "definition": {"col_kind": "LAB"}}})
    assert len(cs) == 1 and cs[0].fit == {"hits": 2, "total": 3}
    geom = {"bits_per_frame": 100, "FX": {"4": 40}, "vy0": 5, "vpitch": 10}
    assert mt.predict(cs[0], (4, 2, geom)) == [40 * 100 + 26, 43 * 100 + 21]
    assert mt.verify(cs[0], (4, 2, geom), [4026, 4321]) == "confirmed"
    assert mt.verify(cs[0], (4, 2, geom), [4026]) == "refuted"
    assert mt.propose({"tiles": {(10, 10): tiles[(10, 10)]}, "parents": {}, "subject": "x",
                       "class_scope": {"space": "bit", "kind": "tile-class", "definition": {}}}) == []


def test_per_column_offset_stops_at_non_lab_columns():
    import pattern_matchers as PM
    mt = PM.PerColumnOffset()
    c = mt.propose({"anchors": {"2": 0, "6": 1}, "columns": [1, 2, 3, 4, 5, 6, 7], "col_kind": {"4": "M9K"},
                    "parents": [1], "subject": "asm->plane", "scope": {"space": "coord-map", "kind": "keys", "definition": {"keys": ["asm->plane"]}}})[0]
    assert mt.predict(c, 3) == 0 and mt.predict(c, 5) == 1 and mt.predict(c, 7) == 1 and mt.predict(c, 4) is None


def test_statistical_matcher_is_separate_type():
    import pattern_matchers as PM
    assert issubclass(PM.VoteMatcher, PM.StatisticalMatcher) and PM.VoteMatcher.kind == "statistical"
    assert not issubclass(PM.BitLinearLaw, PM.StatisticalMatcher) and PM.BitLinearLaw.kind == "deterministic"
    c = PM.VoteMatcher().propose({"votes": {"wire:k": {'"a"': 9, '"b"': 1}}, "parents": [], "scope": {"space": "mux-input", "kind": "keys", "definition": {"keys": ["k"]}}})[0]
    assert c.law["value"] == "a" and c.confidence == 0.9


def test_register_writes_expectations_never_claims(tmp_path, monkeypatch):
    db_path = str(tmp_path / "pm.db")
    monkeypatch.setenv("PLURIBUS_SQLITE_PATH", db_path)
    import db
    db.BACKEND, db._SQPATH, db._engine = "sqlite", db_path, None
    import schema as S
    S.init()
    import pattern_matchers as PM
    m = {str(w): law(w) for w in range(0, 512)}
    mt = PM.BitLinearLaw()
    with db.engine().begin() as conn:
        conn.execute(insert(S.families).values(id="cycloneiv", vendor="altera", name="Cyclone IV", lut_inputs=4, bit_model="frame,v"))
        ev = conn.execute(insert(S.evidence).values(kind="specimen-pair", family="cycloneiv", device="EP4CGX150", name="p", source_ref="s",
                                                    result={}, commit=COMMIT)).inserted_primary_key[0]
        cs = mt.propose({"subject": "M9K:init:w1", "index_to_cell": m, "parents": [ev],
                         "scope": {"space": "cell-param", "kind": "keys", "definition": {"keys": ["M9K:init:w1"]}, "n_objects": 9216}})
        ids = PM.register_expectations(conn, mt, cs, "cycloneiv", "EP4CGX150", COMMIT)
        ids2 = PM.register_expectations(conn, mt, cs, "cycloneiv", "EP4CGX150", COMMIT)
        assert ids == ids2                                    # idempotent
        assert conn.execute(select(S.claims)).fetchall() == []  # never a claim
        e = conn.execute(select(S.expectations)).fetchone()
        assert e.matcher_id == "affine-v1" and e.status == "open" and e.n_objects == 9216 and e.confidence == 1.0
        p = conn.execute(select(S.claim_patterns)).fetchone()
        assert p.matcher_id == "affine-v1" and p.status == "open"
        assert conn.execute(select(S.pattern_evidence.c.evidence_id)).scalar() == ev
    db._engine = None


def test_llm_proposer_dry_run_and_gate(monkeypatch, capsys):
    import pattern_proposer_llm as L
    train = {str(w): law(w) for w in range(0, 1024) if w % 3}      # every index bit exercised
    held = {str(w): law(w) for w in range(0, 1024) if not w % 3}
    user = L.build_prompt("M9K:init:w1", train, held)
    assert "predict for:" in user and L.estimate_tokens(user) > 100
    good = {"kind": "bit-linear", "params": {}, "predictions": {k: v for k, v in held.items()}, "confidence": 0.9}
    bad = {"kind": "bit-linear", "params": {}, "predictions": {"201": [0, 0]}}   # 201 is held out: a wrong prediction
    other = {"kind": "magic"}
    acc = L.check_candidates([good, bad, other], train, held, [1], "M9K:init:w1")
    assert len(acc) == 1 and acc[0].law["proposed_by"]["matcher"] == "llm-proposer-v1"
    assert L.parse_candidates('text {"candidates": [{"kind": "bit-linear"}]} more')[0]["kind"] == "bit-linear"
    assert L.parse_candidates("no json") == []
    assert L.cost_usd("claude-opus-5-5", 1_000_000, 0) == pytest.approx(4.0)
