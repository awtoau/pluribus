"""Provenance framework (docs/provenance-schema.md): temp SQLite, no server, no pytrellis.

Covers: tier immutability, weakest-link derivation, refutation fan-out (pattern suspect -> siblings
suspect -> audits queued), conflict status, corpus-pass done criterion (park + reopen), expectations vs
unknowns, evidence bit packing + record_specimen round trip, scope expansion, export/import round trip.
"""
import os
import sys

import numpy as np
import pytest
from sqlalchemy import insert, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

COMMIT = "deadbeef"
GEOM = {"bits_per_frame": 100, "FX": {"1": 10, "2": 20, "3": 30, "4": 40}, "vy0": 5, "vpitch": 10, "ymax": 4,
        "col_kind": {"1": "LAB", "2": "LAB", "3": "M9K", "4": "LAB"}}


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "prov.db")
    monkeypatch.setenv("PLURIBUS_DB_BACKEND", "sqlite")
    monkeypatch.setenv("PLURIBUS_SQLITE_PATH", db_path)
    import db
    db.BACKEND, db._SQPATH, db._engine = "sqlite", db_path, None
    import schema
    schema.init()
    yield db_path
    db._engine = None


def eng():
    import db
    return db.engine()


def seed(conn):
    """family + device + 1 evidence + 1 pattern + 3 claims citing it + 1 expectation + 1 unknown."""
    import schema as S
    from provenance import evidence_io as E
    conn.execute(insert(S.families).values(id="fam", vendor="v", name="F", lut_inputs=4, bit_model="frame,v"))
    conn.execute(insert(S.devices).values(family="fam", name="dev", geometry=GEOM, die_bits=10000))
    conn.execute(insert(S.matchers).values(id="m-v1", kind="deterministic", name="m", version=1, code_ref="x", created_commit=COMMIT))
    ev = E.record_specimen(conn, "fam", "dev", "pair1", "base1", [[1, 5], [1, 7]], [], {"src": 0}, "ev/pair1.json",
                           "gen.py", COMMIT, 100)
    ev2 = E.record_specimen(conn, "fam", "dev", "pair2", "base1", [[2, 5]], [], {"src": 1}, "ev/pair2.json", "gen.py", COMMIT, 100)
    conn.execute(insert(S.claim_patterns).values(id="law-v1", family="fam", device="dev", matcher_id="m-v1", space="bit",
                                                 description="d", law={"dims": 1}, status="open", created_commit=COMMIT))
    conn.execute(insert(S.pattern_evidence).values(pattern_id="law-v1", evidence_id=ev, role="parent"))
    from provenance import scopes as SC
    scopes = {}
    for i in range(4):
        d = {"x": 1, "y": i, "offsets": [[0, 0]]}
        sid = conn.execute(insert(S.scopes).values(family="fam", device="dev", space="bit", kind="tile",
                                                   scope_key=SC.canonical("bit", "tile", d), definition=d,
                                                   n_objects=10 * (i + 1))).inserted_primary_key[0]
        scopes[i] = sid
    base = conn.execute(insert(S.claims).values(family="fam", device="dev", space="bit", subject_key="s", scope_id=scopes[0],
                                                meaning={"v": 1}, tier="measured", status="confirmed", n_objects=10,
                                                created_commit=COMMIT)).inserted_primary_key[0]
    conn.execute(insert(S.claim_evidence).values(claim_id=base, evidence_id=ev, role="direct"))
    pred = []
    for i in (1, 2, 3):
        cid = conn.execute(insert(S.claims).values(family="fam", device="dev", space="bit", subject_key="s", scope_id=scopes[i],
                                                   meaning={"v": 1}, tier="pattern-predicted", status="open", pattern_id="law-v1",
                                                   n_objects=10 * (i + 1), created_commit=COMMIT)).inserted_primary_key[0]
        pred.append(cid)
    exp = conn.execute(insert(S.expectations).values(family="fam", device="dev", space="bit", subject_key="t", scope_id=scopes[3],
                                                     matcher_id="m-v1", pattern_id="law-v1", expected={"v": 2}, status="open",
                                                     n_objects=40, created_commit=COMMIT)).inserted_primary_key[0]
    unk_e = conn.execute(insert(S.unknowns).values(family="fam", device="dev", space="bit", subject_key="t", scope_id=scopes[3],
                                                   reason="unasked", status="open", n_objects=40, created_commit=COMMIT)).inserted_primary_key[0]
    unk_s = conn.execute(insert(S.unknowns).values(family="fam", device="dev", space="bit", subject_key="u", scope_id=scopes[2],
                                                   reason="unasked", status="open", n_objects=30, created_commit=COMMIT)).inserted_primary_key[0]
    return dict(ev=ev, ev2=ev2, base=base, pred=pred, exp=exp, unk_expected=unk_e, unk_serious=unk_s, scopes=scopes)


# ── vocabulary / tiers ───────────────────────────────────────────────────────

def test_vocabulary_is_closed():
    from provenance import tiers
    assert tiers.weakest(["measured", "statistical", "vendor-decoded"]) == "statistical"
    assert tiers.weakest([]) == "unknown"
    assert tiers.weakest_status(["confirmed", "suspect", "open"]) == "suspect"
    with pytest.raises(SystemExit):
        tiers.check("decoded", tiers.TIERS, "tier")


def test_tier_fixed_at_creation_status_moves():
    import schema as S
    from provenance import feedback as F
    with eng().begin() as conn:
        s = seed(conn)
        F.refute(conn, s["pred"][0], s["ev2"], COMMIT)
        F.confirm(conn, s["base"], s["ev2"], COMMIT)
        rows = {r.id: r for r in conn.execute(select(S.claims))}
    assert rows[s["pred"][0]].tier == "pattern-predicted" and rows[s["pred"][0]].status == "refuted"
    assert rows[s["base"]].tier == "measured" and rows[s["base"]].confirmations == 1


def test_weakest_link_through_pattern_parents():
    """pattern-predicted claim whose pattern was fitted on evidence that a statistical claim rests on -> statistical."""
    import schema as S
    from provenance import feedback as F
    with eng().begin() as conn:
        s = seed(conn)
        assert F.effective_tier(conn, s["pred"][1]) == "pattern-predicted"
        # a statistical claim also rests directly on the parent evidence (e.g. afx_map placement)
        from provenance import scopes as SC
        sid = conn.execute(insert(S.scopes).values(family="fam", device="dev", space="coord-map", kind="keys",
                                                   scope_key=SC.canonical("coord-map", "keys", {"keys": ["x1"]}),
                                                   definition={"keys": ["x1"]}, n_objects=1)).inserted_primary_key[0]
        stat = conn.execute(insert(S.claims).values(family="fam", device="dev", space="coord-map", subject_key="afx", scope_id=sid,
                                                    meaning={}, tier="statistical", status="open", n_objects=1,
                                                    created_commit=COMMIT)).inserted_primary_key[0]
        conn.execute(insert(S.claim_evidence).values(claim_id=stat, evidence_id=s["ev"], role="direct"))
        assert F.effective_tier(conn, s["pred"][1]) == "statistical"
        # explicit dependency in meaning.depends_on
        dep = conn.execute(insert(S.claims).values(family="fam", device="dev", space="bit", subject_key="placed", scope_id=sid,
                                                   meaning={"depends_on": [stat]}, tier="vendor-decoded", status="open", n_objects=1,
                                                   created_commit=COMMIT)).inserted_primary_key[0]
        assert F.effective_tier(conn, dep) == "statistical"


# ── feedback loop ────────────────────────────────────────────────────────────

def test_refutation_fans_out_to_siblings_and_audits():
    import schema as S
    from provenance import feedback as F
    from provenance import queries as Q
    with eng().begin() as conn:
        s = seed(conn)
        out = F.refute(conn, s["pred"][0], s["ev2"], COMMIT)
        assert out["pattern"] == "law-v1" and out["siblings"] == 2
        st = {r.id: r.status for r in conn.execute(select(S.claims))}
        assert st[s["pred"][0]] == "refuted" and st[s["pred"][1]] == "suspect" and st[s["pred"][2]] == "suspect"
        assert st[s["base"]] == "confirmed"          # measured claim untouched
        pat = conn.execute(select(S.claim_patterns.c.status)).scalar()
        assert pat == "suspect"
        q = Q.audit_queue(conn, "fam")
        assert len(q) == 2                           # one audit per (pattern, scope): the expectation shares scope 3 with a sibling
        assert q[0]["priority"] >= q[-1]["priority"]
        assert Q.suspect_patterns(conn, "fam")[0]["id"] == "law-v1"
        ev = [r.event for r in conn.execute(select(S.claim_events))]
        assert ev.count("suspect") == 3 and "refuted" in ev
        with pytest.raises(SystemExit):              # 'mostly holds' is not an exit
            F.clear_pattern(conn, "law-v1", COMMIT)


def test_blast_radius_queries():
    from provenance import queries as Q
    with eng().begin() as conn:
        s = seed(conn)
        r = Q.resting_on(conn, s["ev"])
        ids = {c["id"] for c in r["claims"]}
        assert ids == {s["base"], *s["pred"]} and r["patterns"] == ["law-v1"]
        assert len(r["expectations"]) == 1
        f = Q.flips_if_wrong(conn, s["ev"])
        assert f["by_pattern"]["law-v1"]["claims"] == 3 and f["n_objects"] == 10 + 20 + 30 + 40 + 40
        assert Q.by_pattern(conn, "law-v1")["n_objects"] == 20 + 30 + 40 + 40
        assert Q.by_matcher(conn, "m-v1")["patterns"][0]["id"] == "law-v1"


def test_conflict_is_first_class():
    import schema as S
    from provenance import feedback as F
    from provenance import queries as Q
    with eng().begin() as conn:
        s = seed(conn)
        # a second source on the same subject: its own scope row (same subject + scope is the unique key)
        from provenance import scopes as SC
        sid = conn.execute(insert(S.scopes).values(family="fam", device="dev", space="bit", kind="keys",
                                                   scope_key=SC.canonical("bit", "keys", {"keys": ["s"]}),
                                                   definition={"keys": ["s"]}, n_objects=10)).inserted_primary_key[0]
        other = conn.execute(insert(S.claims).values(family="fam", device="dev", space="bit", subject_key="s", scope_id=sid,
                                                     meaning={"v": 9}, tier="vendor-decoded", status="open", n_objects=10,
                                                     created_commit=COMMIT, pattern_id=None)).inserted_primary_key[0]
        cid = F.conflict(conn, s["base"], other, COMMIT)
        st = {r.id: r.status for r in conn.execute(select(S.claims))}
        assert st[s["base"]] == "conflict" and st[other] == "conflict"
        assert Q.conflicts(conn, "fam")[0]["status"] == "open"
        F.adjudicate(conn, cid, s["base"], "specimen wins", COMMIT)
        st = {r.id: r.status for r in conn.execute(select(S.claims))}
        assert st[s["base"]] == "confirmed" and st[other] == "refuted"


def test_expectation_confirmed_becomes_measured_claim_and_promotes_unknown():
    import schema as S
    from provenance import feedback as F
    from provenance import queries as Q
    with eng().begin() as conn:
        s = seed(conn)
        assert {u["id"] for u in Q.seriously_unknown(conn, "fam")} == {s["unk_serious"]}
        assert {u["unknown_id"] for u in Q.expected_unknowns(conn, "fam")} == {s["unk_expected"]}
        cid = F.confirm_expectation(conn, s["exp"], s["ev2"], COMMIT)
        c = conn.execute(select(S.claims).where(S.claims.c.id == cid)).fetchone()
        assert c.tier == "measured" and c.status == "confirmed" and c.pattern_id is None
        e = conn.execute(select(S.expectations.c.status, S.expectations.c.claim_id)).fetchone()
        assert e == ("confirmed", cid)
        u = conn.execute(select(S.unknowns.c.status).where(S.unknowns.c.id == s["unk_expected"])).scalar()
        assert u == "promoted"
        assert len(Q.open_expectations(conn, "fam")) == 0


def test_expectation_refuted_makes_pattern_suspect():
    from provenance import feedback as F
    from provenance import queries as Q
    with eng().begin() as conn:
        s = seed(conn)
        out = F.refute_expectation(conn, s["exp"], s["ev2"], COMMIT, observed={"v": 3})
        assert out["pattern"] == "law-v1" and out["siblings"] == 3
        assert Q.suspect_patterns(conn, "fam")[0]["id"] == "law-v1"


def test_supersede_rejects_weaker():
    import schema as S
    from provenance import feedback as F
    with eng().begin() as conn:
        s = seed(conn)
        with pytest.raises(SystemExit):
            F.supersede(conn, s["base"], s["pred"][0], COMMIT)   # measured cannot be superseded by predicted
        F.supersede(conn, s["pred"][0], s["base"], COMMIT)
        r = conn.execute(select(S.claims.c.status, S.claims.c.superseded_by).where(S.claims.c.id == s["pred"][0])).fetchone()
        assert r == ("superseded", s["base"])


# ── corpus / done criterion ──────────────────────────────────────────────────

def test_done_criterion_parks_then_reopens_failing_cone():
    import schema as S
    from provenance import corpus as C
    from provenance import queries as Q
    with eng().begin() as conn:
        s = seed(conn)
        C.ensure_member(conn, "fam", "d1", "oracle-build", COMMIT)
        C.ensure_member(conn, "fam", "d2", "oracle-build", COMMIT)
        C.ensure_member(conn, "fam", "img", "third-party-image", COMMIT, required=False)
        ok = {"pips": {"matched": 10, "missing": 0, "extra": 0, "wrong": 0}, "nets": {"matched": 5, "missing": 0, "extra": 0, "wrong": 0}}
        run = C.record_gate_run(conn, "fam", "gate.py", COMMIT, {"d1": ok, "d2": ok})
        d = Q.done_state(conn, "fam")
        assert d["state"] == "met" and d["met_now"] and d["passing"] == 2
        assert conn.execute(select(S.gate_runs.c.passed).where(S.gate_runs.c.id == run)).scalar() is True
        parked = Q.parked(conn, "fam")
        assert len(parked["unknowns"]) == 2 and len(parked["expectations"]) == 1
        assert parked["unknowns"][0]["reason"] == "not-required-by-corpus"
        assert Q.seriously_unknown(conn, "fam") == []        # parked rows leave the open view, still queryable
        # missing counts as a fault: headline < 100 fails even with wrong == 0
        bad = dict(ok, pips={"matched": 9, "missing": 1, "extra": 0, "wrong": 0, "failing_claims": [s["pred"][2]]})
        conn.execute(insert(S.lift_provenance).values(bitstream=None, object_kind="lut", object_key="x", min_tier="pattern-predicted",
                                                      min_status="open", claim_ids=[s["pred"][2]])) if False else None
        C.record_gate_run(conn, "fam", "gate.py", COMMIT, {"d1": ok, "d2": bad})
        d = Q.done_state(conn, "fam")
        assert d["state"] == "open" and not d["met_now"]
        st = {r.id: r.status for r in conn.execute(select(S.claims))}
        assert st[s["pred"][2]] == "suspect" and st[s["pred"][1]] == "suspect"   # cone claim + pattern siblings
        assert st[s["base"]] == "confirmed"
        # exactly the items on the failing cone's scope reopen; the other parked unknown stays parked
        us = {r.id: r.status for r in conn.execute(select(S.unknowns))}
        assert us[s["unk_expected"]] == "open" and us[s["unk_serious"]] == "parked"
        es = conn.execute(select(S.expectations.c.status)).scalar()
        assert es == "open"
        assert any(a["reason"] == "corpus-fail" for a in Q.audit_queue(conn, "fam"))
        cs = Q.corpus_state(conn, "fam")
        m = {x["member"]: x for x in cs["members"]}
        assert m["d2"]["passed"] is False and m["d2"]["missing"] == 1 and m["img"]["required"] is False


def test_headline_counts_every_fault():
    from provenance import corpus as C
    assert C.headline({"matched": 6, "missing": 2, "extra": 1, "wrong": 1}) == 60.0
    assert not C.member_passes([{"matched": 6, "missing": 0, "extra": 1, "wrong": 0}])
    assert C.member_passes([{"matched": 6, "missing": 0, "extra": 0, "wrong": 0}])


# ── evidence packing / scopes / export ───────────────────────────────────────

def test_bit_packing_round_trip():
    from provenance import evidence_io as E
    idx = np.array([0, 1, 5, 6368, 39425015, 2**33], np.int64)
    assert np.array_equal(E.unpack(E.pack(idx)), idx)
    assert E.unpack(b"").size == 0
    assert len(E.pack(np.arange(1000))) == 1000          # dense: one byte per bit
    assert E.to_flat([[1, 5], [1, 7]], 100).tolist() == [105, 107]


def test_record_specimen_round_trip_and_idempotent():
    import schema as S
    from provenance import evidence_io as E
    with eng().begin() as conn:
        s = seed(conn)
        again = E.record_specimen(conn, "fam", "dev", "pair1", "base1", [[1, 5], [1, 7]], [], {"src": 0}, "ev/pair1.json",
                                  "gen.py", COMMIT, 100)
        assert again == s["ev"]
        pairs = E.pairs_from_db(conn, "fam", "dev", "ev/pair1.json")
        assert pairs["pair1"]["only_spec"] == [105, 107] and pairs["pair1"]["meta"] == {"src": 0}
        assert E.canonical_hash(pairs) == E.canonical_hash({"pair1": {"base": "base1", "only_spec": [107, 105], "only_base": [], "meta": {"src": 0}}})
        r = conn.execute(select(S.evidence.c.bit_encoding, S.evidence.c.n_objects).where(S.evidence.c.id == s["ev"])).fetchone()
        assert r == ("dvarint:flat:100", 2)


def test_scope_expansion():
    from provenance import scopes as SC
    t = SC.expand("tile", {"x": 2, "y": 1, "offsets": [[0, 0], [1, -2]]}, GEOM)
    assert t.tolist() == [20 * 100 + 15, 21 * 100 + 13]
    tc = SC.expand("tile-class", {"col_kind": "LAB", "offsets": [[0, 0]], "y_range": [1, 2]}, GEOM)
    assert len(tc) == 3 * 2                                       # 3 LAB columns x 2 rows
    assert SC.count("tile-class", {"col_kind": "LAB", "offsets": [[0, 0], [1, 1]], "count_only": True}, GEOM) == 3 * 3 * 2
    assert SC.expand("range", {"frames": [1, 2], "v": [0, 1]}, GEOM).tolist() == [100, 101, 200, 201]
    assert SC.intersects("tile", {"x": 2, "y": 1, "offsets": [[0, 0]]}, "range", {"frames": [20, 20]}, GEOM)
    assert SC.canonical("bit", "keys", {"keys": ["b", "a"]}) == 'bit|keys|{"keys":["b","a"]}'
    with pytest.raises(SystemExit):
        SC.expand("formula", {"matcher": "x"})


def test_export_import_round_trip(tmp_path):
    import provenance_export as X
    from provenance import corpus as C
    from provenance import feedback as F
    with eng().begin() as conn:
        s = seed(conn)
        F.refute(conn, s["pred"][0], s["ev2"], COMMIT)
        C.ensure_member(conn, "fam", "d1", "oracle-build", COMMIT)
        C.record_gate_run(conn, "fam", "gate.py", COMMIT, {"d1": {"pips": {"matched": 1, "missing": 1, "extra": 0, "wrong": 0}}})
    out = tmp_path / "exp"
    with eng().connect() as conn:
        sizes = X.export(conn, "fam", out)
    assert sizes["claims"][0] == 4 and sizes["audits"][0] == 2 and sizes["gate_results"][0] == 1
    assert X.check("fam", out)
