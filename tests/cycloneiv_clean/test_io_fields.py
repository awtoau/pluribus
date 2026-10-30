"""IO field decode (#168): vendor select law (io_encode) and the table-driven site decoder (io_fields).  Skips when local data is missing.

Missing is a fault: class / field counts are logged to tmp/logs/cycloneiv_clean_oracles.log.
"""
import collections
import json

import pytest

from conftest import report
from lifters.cycloneiv_clean import io_decode as D
from lifters.cycloneiv_clean import io_encode as E
from lifters.cycloneiv_clean import io_fields as F


@pytest.fixture(scope="module")
def table():
    from conftest import need
    need(D.DECODE_PATH)
    return json.load(open(D.DECODE_PATH))


@pytest.fixture(scope="module")
def walk():
    from lifters.cycloneiv_clean import asmdb_walk as W
    from lifters.cycloneiv_clean import sofio
    try:
        return W.Walk()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))


@pytest.fixture(scope="module")
def chain():
    from conftest import need
    from lifters.cycloneiv_clean import sofio
    need(D.DECODE_PATH, D.BUILDS)
    try:
        return D.Chain()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))


def test_encode_law_reproduces_every_pair_pattern(chain, walk, table):
    # ENCODED_MUX::select: element k = value bit k, arch_value 1 = no inversion.  Every pair-build pattern of an ENCODED group inverts to a
    # value and re-encodes to itself at a real site (law check), and the 2^n values of each group give 2^n distinct patterns.
    names = chain.names
    groups = {}
    for o in walk.groups():
        if o["btype"] in (5, 6) and o["cls"] in (6, 7):
            groups.setdefault((o["btype"], names.get(o["type"])), o)
    checked = 0
    for e in table["values"]:
        if not e["primary"] or e["group"] not in ("MIO_SET_SLEW_RATE", "MIO_SELECT_IOST_DIRT", "MIO_SET_PULLUP_STRENGTH", "MIO_SET_PULLDOWN_STRENGTH"):
            continue
        g = groups[(6, e["group"])]
        site = next(s for s in range(len(g["paths"])) if len(E.pattern(walk, g, s, 0)) == e["n_elem"])
        v = E.value_of(e["pattern"])
        assert E.pattern(walk, g, site, v) == e["pattern"]
        checked += 1
    allv = {}
    for nm in ("MIO_SET_SLEW_RATE", "MIO_SELECT_IOST_DIRT", "MIO_SET_PULLUP_STRENGTH", "MIO_SET_PULLDOWN_STRENGTH"):
        g = groups[(6, nm)]
        t = E.all_values(walk, g, 0)
        assert len(set(t.values())) == len(t) == 1 << E.width(walk, g, 0)
        allv[nm] = len(t)
    report("io_encode_law", pair_patterns_checked=checked, values_per_group=allv)
    assert checked > 40
    # DUMB groups: value 1 sets the bit (arch_value 1)
    g = groups[(6, "MIO_USE_PULL_UP")]
    assert E.all_values(walk, g, 0) == {0: "0", 1: "1"}


def test_iost_fourth_bit_is_absent(chain, walk):
    # 51 IO sites list the no-bit sentinel as 4th IOST mux bit (3 real CFF bits: values 0..7 only); the pad-less VIO site lists it 4 times
    g = [o for o in walk.groups() if o["btype"] in (5, 6) and chain.names.get(o["type"]) == "MIO_SELECT_IOST_DIRT"]
    cnt = collections.Counter(sum(1 for a in walk.mux(r[0])["bits"] if a == E.NO_BIT) for o in g for r in o["paths"])
    report("io_iost_sentinel", sites_by_absent_bits=dict(cnt))
    assert cnt == {0: 404, 1: 51, 4: 1}


def test_encode_rejects_out_of_range(chain, walk):
    g = next(o for o in walk.groups() if o["btype"] == 6 and o["cls"] == 6 and chain.names.get(o["type"]) == "MIO_SET_SLEW_RATE")
    with pytest.raises(ValueError):
        E.pattern(walk, g, 0, 4)                       # 2-bit mux: value 4 is a vendor internal error


def test_unused_states(table):
    u = table["unused"]
    opts = {s["option"] for s in u["states"]}
    report("io_unused", options=sorted(opts), states=len(u["states"]), fixed=len(u["fixed"]))
    assert opts == set(D.UNUSED_OPTIONS)
    assert all(s["vector"] and not s["conflict"] and s["source"]["builds"] for s in u["states"])
    by = {(s["option"], s["iost_width"]): s["vector"] for s in u["states"]}
    # gnd and unspec are CFF-identical; they differ from tri-state in the strength groups, pull-up differs in the pull-up bit only
    assert by[("gnd", 4)] == by[("unspec", 4)] and by[("gnd", 4)] != by[("tristate", 4)]
    assert by[("pullup", 4)]["MIO_USE_PULL_UP"] == "1" and by[("tristate", 4)]["MIO_USE_PULL_UP"] == "0"
    assert all(v["source"]["builds"] for v in u["fixed"].values())


def test_decoder_states(table):
    dec = F.Decoder(table)
    d = {s["kind"]: s for s in dec.states if s["src"].startswith("default.")}
    r = dec.decode((6, 1), {**{g: d["out"]["vec"][g] for g in F.JOINT}, "MIO_SET_SLEW_RATE": "01", "MIO_USE_PULL_UP": "0", "MIO_USE_BUS_HOLD": "0",
                           "MIO_PIN_MODE": "0", "MIO_TERMINATION_CONTROL_SELECT": "0"})
    assert r["class"] == "used" and r["direction"]["value"] == "output" and r["slew"]["value"] == "2" and r["drive"]["status"] == "default"
    # an unmatched joint vector is MISSING with its raw patterns, never guessed
    bad = dict(d["out"]["vec"], MIO_SET_PULLUP_STRENGTH="10101010")
    r = dec.decode((6, 1), {**bad, "MIO_SET_SLEW_RATE": "01"})
    assert r["class"] == "MISSING" and r["raw"]["MIO_SET_PULLUP_STRENGTH"] == "10101010"


def test_decoder_drive_values(table):
    dec = F.Decoder(table)
    for v in ("4MA", "8MA", "12MA", "16MA"):
        hit = [s for s in dec.states if s["labels"]["drive"] == v and s["kind"] == "out"]
        assert len(hit) >= 1
        r = dec.decode((6, 1), {**hit[0]["vec"], "MIO_SET_SLEW_RATE": "01", "MIO_USE_PULL_UP": "0", "MIO_USE_BUS_HOLD": "0", "MIO_PIN_MODE": "0"})
        assert r["class"] == "used" and v in (r["drive"].get("candidates") or [r["drive"]["value"]])      # 4MA = MINIMUM CURRENT, 16MA = MAXIMUM CURRENT


def test_cram_registered_patterns(table):
    cv = table["cram_values"]
    report("io_cram_values", entries=len(cv))
    assert cv and all(e["source"]["pairs"] and e["source"]["groups"] for e in cv)
    assert all(len(e["patterns"]) == 1 for e in cv)      # every site agrees on base and spec (zero tolerance)
