"""IO setting tables from the asmdb dirt (vendor data) vs the pair-build patterns (#168).  Missing is a fault: counts are logged."""
import os

import numpy as np
import pytest

from conftest import need, report
from lifters.cycloneiv_clean import io_dirt as T
from lifters.cycloneiv_clean import io_encode as E


@pytest.fixture(scope="module")
def tables():
    from lifters.cycloneiv_clean import sofio
    try:
        return T.tables()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))
    except FileNotFoundError as e:
        pytest.skip(str(e))


@pytest.fixture(scope="module")
def table():
    import json
    from lifters.cycloneiv_clean import io_decode as D
    need(D.DECODE_PATH)
    return json.load(open(D.DECODE_PATH))


# source: DEV_IO_STANDARD_ENUM debug strings (libddb_dstr) of the dirt IO_STANDARD keys vs the QSF names of the pair builds
QSF = {"2_5": "2.5 V", "LVTTL": "3.3-V LVTTL", "LVTTL_30": "3.0-V LVTTL", "LVCMOS": "3.3-V LVCMOS", "LVCMOS_30": "3.0-V LVCMOS", "PCI_30": "3.0-V PCI",
       "1_8": "1.8 V", "1_5": "1.5 V", "1_2": "1.2 V", "SSTL_2_I": "SSTL-2 Class I", "SSTL_18_I": "SSTL-18 Class I", "HSTL_I": "1.5-V HSTL Class I",
       "HSTL_18_I": "1.8-V HSTL Class I"}


def test_iost_values_vs_pair_builds(tables, table):
    dirt = dict(tables[("MIO_SELECT_IOST_DIRT", "VIO")])
    same, diff = [], []
    for e in table["values"]:
        if e["setting"] != "standard" or e["group"] != "MIO_SELECT_IOST_DIRT" or not e["primary"] or e["pattern"] is None:
            continue
        key = next((k for k, v in QSF.items() if v == e["value"]), None)
        if key is None:
            continue
        got = E.value_of(e["pattern"])
        (same if got == dirt[key] else diff).append((e["base_kind"], e["value"], got, dirt[key]))
    report("io_dirt_iost", equal=len(same), differ=len(diff), differ_rows=sorted({(k, v) for k, v, g, d in diff}))
    # every input / bidir pair build and every voltage-class output build equals the dirt value of its standard
    assert not [d for d in diff if d[0] in ("in", "bidir")]
    # outputs of the reference-voltage standards take the value of their VCCIO class (measured 4 of 4)
    assert {v for k, v, g, d in diff} == {"SSTL-2 Class I", "SSTL-18 Class I", "1.5-V HSTL Class I", "1.8-V HSTL Class I"}
    assert len(same) >= 30


def test_unused_pin_is_iost_value_3(tables, table):
    st = [s for s in table["unused"]["states"] if s["option"] == "tristate" and s["iost_width"] == 4][0]
    assert E.value_of(st["vector"]["MIO_SELECT_IOST_DIRT"]) == 3          # ASM_IO_SELECT_IOST::process_atom: reserved pin -> mux_select(.., 3)


def test_strength_2p5v_8ma_equals_dirt(tables, table):
    pd = dict(tables[("MIO_SET_PULLDOWN_STRENGTH", "VIO")])["2.5V"]
    pu = dict(tables[("MIO_SET_PULLUP_STRENGTH", "VIO")])["2.5V"]
    pat = {(e["value"], e["group"]): e["pattern"] for e in table["values"] if e["setting"] == "drive" and e["base_kind"] == "out" and e["primary"]}
    assert E.value_of(pat[("8MA", "MIO_SET_PULLDOWN_STRENGTH")]) == pd == 29
    assert E.value_of(pat[("8MA", "MIO_SET_PULLUP_STRENGTH")]) == pu == 42


def test_lvds_input_builds(tables):
    base = os.path.join(T.P.REPO, "tmp", "cycloneiv_clean", "io_lvds_in")
    need(base)
    from lifters.cycloneiv_clean import io_decode as D
    ch = D.Chain()
    n = 0
    for pin in sorted(os.listdir(base)):
        fb, fl = (os.path.join(base, pin, t, "result.npz") for t in ("base", "lvds"))
        if not (os.path.exists(fb) and os.path.exists(fl)):
            continue
        b, z = np.load(fb)["cff"], np.load(fl)["cff"]
        s = ch.ball_site[pin]
        iost = lambda site, a: "".join(str(int(a[x])) for x in ch.cff[site]["MIO_SELECT_IOST_DIRT"])
        assert E.value_of(iost(s, z)) == dict(tables[("MIO_SELECT_IOST_DIRT", "VIO")])["LVDS"] == 11
        fn = ch.site_pad[s][1].split(",")[0].strip()
        nsite = next(k for k, v in ch.site_pad.items() if v[1].split(",")[0].strip() == fn[:-1] + "n")
        assert E.value_of(iost(nsite, z)) == 11          # the n companion carries the same IOST value (its base was the unused value 3: only bit 3 changes)
        n += 1
    report("io_dirt_lvds", pins=n)
    assert n >= 1
