"""IO decode: asmdb groups (A) x pair-build labels (B) cross-check and the decoded value table (#168).  Skips when local data is missing.

Missing is a fault: per-field matched / missing / extra counts are logged to tmp/logs/cycloneiv_clean_oracles.log, not only asserted.
"""
import collections
import os

import pytest

from conftest import REPO, need, report
from lifters.cycloneiv_clean import io as IO
from lifters.cycloneiv_clean import io_decode as D


@pytest.fixture(scope="module")
def chain():
    from lifters.cycloneiv_clean import sofio
    need(IO.PAIRS_PATH, D.BUILDS)
    try:
        return D.Chain()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))


@pytest.fixture(scope="module")
def pairs():
    return IO.io_pairs()


@pytest.fixture(scope="module")
def table(chain, pairs):
    return D.decode(chain, pairs)


def test_anchor_is_slew_group_min(table):
    a = table["anchor"]
    report("io_decode_anchor", **a)
    assert a["equal_to_pair_location"] == a["sites"] == 20          # site -> anchor from A equals the pair-derived anchor, 20 / 20


def test_cross_check_counts(table):
    cc = {k: v for k, v in table["cross_check"].items() if not k.startswith("_")}
    report("io_decode_cross_check", **{k: {c: v[c] for c in ("matched", "missing", "extra", "wrong", "extra_coupled", "extra_foreign",
                                                           "extra_unowned", "sites")} for k, v in cc.items()})
    want = {"slew": (40, 0, 0), "pull-up": (20, 0, 0), "bus-hold": (20, 0, 0), "drive": (260, 80, 0), "standard": (60, 14, 412),
            "termination": (0, 20, 140), "direction": (0, 20, 200), "open-drain": (0, 20, 0)}
    assert {k: (cc[k]["matched"], cc[k]["missing"], cc[k]["extra"]) for k in want} == want
    assert all(v["wrong"] == 0 for v in cc.values())
    # every extra bit of a field sits in a group of A (same site or another site): none unowned
    assert all(v["extra_unowned"] == 0 for v in cc.values())


def test_foreign_standard_bits_are_vref_pads(chain, table):
    # the extra standard bits are IOST bits of the VREF pad of the pin's bank (bank 3 also nCEO): 20 / 20 sites
    fo = table["cross_check"]["_foreign_owner_sites"]
    funcs = collections.Counter()
    for pin, v in fo.items():
        fs = [chain.site_pad[tuple(o)][1] for o in v["owners"]]
        funcs.update(f.split(",")[-1].strip()[:5] for f in fs)
        assert any(f.startswith("VREFB") for f in fs), (pin, fs)
    report("io_decode_vref_owner", sites=len(fo), functions=dict(funcs))
    assert len(fo) == 20


def test_value_table_site_independent(table):
    prim = [e for e in table["values"] if e["primary"]]
    bad = [e for e in prim if e["sites_agree"] != e["sites"]]
    report("io_decode_values", entries=len(table["values"]), primary=len(prim), primary_disagreeing=len(bad))
    assert prim and not bad                 # every primary field value has one bit pattern at all sites of its group size
    assert all(e["source"]["pairs"] and e["source"]["groups"] for e in table["values"])


def test_slew_values(table):
    got = {e["value"]: e["pattern"] for e in table["values"] if e["setting"] == "slew" and e["base_kind"] == "out" and e["primary"]}
    assert got == {"0": "00", "1": "10", "2": "01"}         # element i = value bit i; default (unassigned) = slew 2
    d = {e["pattern"] for e in table["values"] if e["setting"] == "default" and e["base_kind"] == "out" and e["group"] == "MIO_SET_SLEW_RATE"}
    assert d == {"01"}


def test_drive_values(table):
    pat = {(e["value"], e["group"]): e["pattern"] for e in table["values"] if e["setting"] == "drive" and e["base_kind"] == "out" and e["primary"]}
    for a, b in (("4MA", "MINIMUM CURRENT"), ("16MA", "MAXIMUM CURRENT")):
        assert pat[(a, "MIO_SET_PULLUP_STRENGTH")] == pat[(b, "MIO_SET_PULLUP_STRENGTH")]
        assert pat[(a, "MIO_SET_PULLDOWN_STRENGTH")] == pat[(b, "MIO_SET_PULLDOWN_STRENGTH")]
    assert len({(pat[(v, "MIO_SET_PULLUP_STRENGTH")], pat[(v, "MIO_SET_PULLDOWN_STRENGTH")]) for v in ("4MA", "8MA", "12MA", "16MA")}) == 4


def test_boolean_fields(table):
    for st in ("pull-up", "bus-hold"):
        assert {e["pattern"] for e in table["values"] if e["setting"] == st and e["primary"]} == {"1"}
    assert {e["pattern"] for e in table["values"] if e["setting"] == "default" and e["group"] in ("MIO_USE_PULL_UP", "MIO_USE_BUS_HOLD")} <= {"0"}


def test_cram_fields(table):
    cf = table["cram_fields"]
    report("io_decode_cram", **{k: v["groups"] for k, v in cf.items()})
    assert "MIO_PIN_MODE" in cf["registered-oe"]["groups"] and "MIO_REG_FEEDS_PIN_OUT" in cf["registered-output"]["groups"]
    assert {"MIO_INREG_CLK_FAST_MUX", "MIO_USE_CLR_INREG"} <= set(cf["registered-input"]["groups"])
    assert cf["open-drain"]["groups"] == {}                 # the assignment builds are bit-identical (no CRAM, no CFF)


def test_double_group_bits(table):
    dg = table["double_groups"]
    report("io_decode_double_groups", **dg)
    assert set(dg) == {"4521", "6952"}
    for v in dg.values():
        assert v["g1_changed"] == 0 and v["g2_changed"] == v["rows"]      # the value sits in the second cell group


def test_open_drain_is_pin_mode_bit(table):
    od = table["open_drain"]
    if not od:
        pytest.skip("od builds missing: python3.15t scripts/cycloneiv_clean_io_od.py")
    report("io_decode_open_drain", sites=len(od), diff=[o["diff"] for o in od])
    for o in od:
        assert set(o["diff"].values()) == {"MIO_PIN_MODE"} and len(o["diff"]) == 1
        assert o["pin_mode_pattern"] == {"out": "0", "od": "1"}
