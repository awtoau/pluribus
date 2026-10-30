"""Mux classes 21 (ENCODED_BANK), 22 (RAM), 24 (STL_MAPPED_ENCODED) and group classes 7 / 8 select rules (ledger B-004).

Rules from libdb_asmdb static decompile: ENCODED_BANK_MUX::select@0x8bfac, RAM_MUX::select@0x86bc4 / 0x8bdca, STLMAP::select@0x7b28c, DUMB::select@0x78f4c.
"""
import pytest

from conftest import need
from lifters.cycloneiv_clean import asmdb_select as S
from lifters.cycloneiv_clean import asmdb_walk as W


@pytest.fixture(scope="module")
def walk():
    from lifters.cycloneiv_clean import sofio
    try:
        return W.Walk()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))


def _first(walk, cls):
    ms = walk.S["MUX"].objs
    i = next(i for i, m in enumerate(ms) if i and m["cls"] == cls)
    return ("MUX", i), ms[i]


def test_encoded_bank(walk):
    ref, m = _first(walk, 21)
    n, bs = m["size"], m["bank"]
    assert len(m["bits"]) == n * bs
    for v in range(1 << n):
        w = S.select(walk, ref, v)
        assert len(w) == n * bs
        for k in range(n):
            assert all(val == (v >> k) & 1 for b, val in w[k * bs:(k + 1) * bs])
    with pytest.raises(ValueError):
        S.select(walk, ref, 1 << n)


def test_ram_mux_content_has_no_polarity_and_is_not_whole_value(walk):
    ref, m = _first(walk, 22)
    assert len(m["bits"]) == 9216 and not m["pol"]          # RAM_CONTENT_YGR_MEAB: bit written as given (m9k 1,210,368 / 0 / 0 / 0)
    assert S.ram_bit(walk, m, 5, 1) == (m["bits"][5], 1) and S.ram_bit(walk, m, 5, 0) == (m["bits"][5], 0)
    with pytest.raises(ValueError):                         # RAM_MUX::select(value): size <= 32
        S.select(walk, ref, 0)


def test_ram_polarity_flip(walk):
    m = {"bits": [10, 11], "pol": ("MUX", 0)}

    class Fake:
        @staticmethod
        def mux(ref):
            return {"bits": [0, 1]}
    assert S.ram_bit(Fake, m, 0, 1) == (10, 1) and S.ram_bit(Fake, m, 1, 1) == (11, 0)


def test_stlmap_group(walk):
    gs = [g for g in walk.groups() if g["cls"] == 8]
    assert len(gs) == 7
    for g in gs:
        for site in range(len(g["paths"])):
            w = S.stl_select(walk, g, site, 0)
            assert w and all(v in (0, 1) for _, v in w)


def test_dumb_polarity():
    assert S.dumb_select({"bits": [7], "arch": 1}, 0, 1) == [(7, 1)]
    assert S.dumb_select({"bits": [7], "arch": 0}, 0, 1) == [(7, 0)]
    assert S.dumb_select({"bits": [7], "arch": 0}, 0, 0) == [(7, 1)]
    with pytest.raises(ValueError):
        S.dumb_select({"bits": [7], "arch": 1}, 0, 2)
