"""#123: ECP5 gate scoring logic (no Diamond, no lift)."""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ecp5_gate as G  # noqa: E402


def counts(m=10, miss=1, extra=0, wrong=0):
    c = {"matched": m, "missing": miss, "extra": extra, "wrong": wrong}
    return {cat: dict(c) for cat in G.CATS}


def test_verdict_map_kinds():
    k = G.kinds({"MATCH": 5, "LIFT_MISSING": 2, "ORACLE_ONLY": 3, "LIFT_ONLY": 4, "MISMATCH": 6})
    assert k == {"matched": 5, "missing": 5, "extra": 4, "wrong": 6}


def test_headline_counts_every_fault():
    c = {"matched": 6, "missing": 2, "extra": 1, "wrong": 1}
    assert G.pct(c) == 60.0


def test_diff_flags_rise_in_any_fault_kind():
    base = {"a": counts()}
    for kind in G.FAULTS:
        cur = {"a": counts()}
        cur["a"]["nets"][kind] += 1
        reg, imp, new, gone = G.diff(base, cur)
        assert reg == [("a", "nets", kind, base["a"]["nets"][kind], cur["a"]["nets"][kind])]
        assert not imp and not new and not gone


def test_diff_improvement_and_new_and_absent():
    base = {"a": counts(), "b": counts()}
    cur = {"a": counts(miss=0), "c": counts()}
    reg, imp, new, gone = G.diff(base, cur)
    assert not reg
    assert len(imp) == len(G.CATS)
    assert new == ["c"] and gone == ["b"]


def test_totals_and_table_roundtrip():
    t = G.totals({"a": counts(), "b": counts(m=5, miss=2)})
    assert t["pips"] == {"matched": 15, "missing": 3, "extra": 0, "wrong": 0}
    assert "pips" in G.table(t, t) and "18" in G.table(t)


def test_committed_baseline_is_well_formed():
    p = G.DEFAULT_BASELINE
    if not os.path.exists(p):
        return
    with open(p) as fh:
        b = json.load(fh)
    assert {"date", "commit", "conditions", "headline"} <= set(b["meta"])
    assert G.totals(b["targets"]) == b["totals"]
    for t in b["targets"].values():
        assert set(t) == set(G.CATS)
