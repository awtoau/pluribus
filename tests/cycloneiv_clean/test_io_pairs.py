"""IO single-setting pair builds (docs/cycloneiv-clean-io.md, #168).  Skips when the local pair data is missing.

Data: databases/cycloneiv/io_pairs.json (local), written by scripts/cycloneiv_clean_io_pairs.py analyse.
Missing is a fault: pairs with no build and bits that differ from the corpus oracle are reported, not hidden.
"""
import collections
import json
import os
import sys

import pytest

from conftest import REPO, need, report

sys.path.insert(0, os.path.join(REPO, "scripts"))
PAIRS = os.path.join(REPO, "databases", "cycloneiv", "io_pairs.json")


@pytest.fixture(scope="module")
def data():
    need(PAIRS)
    return json.load(open(PAIRS))


def test_plan_is_one_assignment_per_pair():
    import cycloneiv_clean_io_pairs as M
    for setting, _, base, spec in M.pair_list():
        if setting == "direction":
            assert base[1] == spec[1] and base[0] != spec[0]       # Verilog differs, assignments identical
        else:                                                   # exactly one key added or changed
            b, s = dict(base[1]), dict(spec[1])
            assert base[0] == spec[0] and len(s) >= len(b) and sum(1 for k in s if b.get(k) != s[k]) == 1 and set(b) <= set(s)


def test_sampling_plan_covers_every_bank():
    import cycloneiv_clean_io_pairs as M
    need(os.path.join(M.OUT, "pins.json"))
    s = M.sample_sites()
    per = collections.Counter(v["bank"] for v in s.values())
    assert len(per) >= 6 and min(per.values()) >= 3            # ends + interior sample per bank (recovery-process.md)
    assert collections.Counter(v["role"] for v in s.values())["end"] == 2 * len(per)


def test_pair_diffs_consistent(data):
    from lifters.cycloneiv_clean import cycloneiv_io as IO
    try:
        cff = IO.Cff()
    except IO.CffMissing as e:
        pytest.skip(str(e))
    ok = [r for r in data["rows"] if r["status"] == "ok"]
    assert ok
    bad = [r for r in ok if not r["rbf_agree"]]
    report("io_pairs_consistency", rows=len(ok), no_build=len(data["rows"]) - len(ok), sof_diff_not_in_rbf_first_group=len(bad),
           replica_bad=sum(r["replica_bad"] for r in ok))
    assert not any(r["replica_bad"] for r in ok)
    assert not bad                    # every sof CFF bit of a pair diff is in the rbf diff (single data group per bit)


def test_pair_results_recorded(data):
    by = collections.defaultdict(list)
    for r in data["rows"]:
        if r["status"] == "ok":
            by[(r["setting"], r["value"], r["base"].split(".")[0])].append(len(r["cff"]))
    report("io_pairs_settings", settings=len(by), bits={f"{a}|{b}|{c}": sorted(set(v)) for (a, b, c), v in by.items()})
    assert len(by) > 0


def test_location_signature_vs_corpus(data):
    cmp = data["location_vs_corpus"]
    have = [c for c in cmp if not c.get("no_oracle")]
    report("io_pairs_location", sites=len(cmp), with_oracle=len(have), matched=sum(c["matched"] for c in have),
           missing=sum(c["missing"] for c in have), extra=sum(c["extra"] for c in have))
    assert cmp
