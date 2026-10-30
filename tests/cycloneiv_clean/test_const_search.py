"""scripts/cycloneiv_clean_const_search.py: constants / CRCs found in hand-built netlists, plus the Quartus CRC specimen when present (skipped otherwise)."""
import os
import pickle
import sys

import numpy as np

from conftest import REPO, need

sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cycloneiv_clean_const_search as CS  # noqa: E402
from lifters.cycloneiv_clean import emit, m9k  # noqa: E402
from test_patterns import fib_netlist, ff  # noqa: E402


def and_lut(pins, name, init):
    return dict(name=name, x=1, y=1, le=0, lab=0, init=init, pins=pins, prod=[None] * 4, rec=[None] * 4, cin=None, mode="datac")


def rom_block(width, words):
    bits = np.zeros(m9k.CONTENT_BITS, np.uint8)
    for w, v in enumerate(words):
        for b in range(width):
            bits[m9k.pos_of_index(m9k.index(width, w, b))] = (v >> b) & 1
    return dict(x=3, y=4, inst=7, content=bits, ctl={}, W=width, A=9, cls=0, modelled=False, be=None, data=[], addr=[], we=None, clk=None, oreg=False, init=[])


def test_m9k_byte_sequence_and_word():
    nl = emit.Netlist("t")
    nl.m9k.append(rom_block(8, [0x11, 0x22, 0xA5, 0x3C, 0x77]))
    consts = {"seq": (bytes([0xA5, 0x3C]), 16), "absent": (bytes([0xDE, 0xAD]), 16)}
    res, populated = CS.search_m9k(nl, consts, {})
    assert populated == 1
    assert any(h["width"] == 8 and h["kind"] == "stream-plain" and h["byte_offset"] == 2 for h in res["seq"])
    assert res["absent"] == []


def test_crc_table_matches_known_vector():
    # CRC-16/CCITT-FALSE table entry for byte 1 and CRC-8 (poly 0x07) entry for byte 1
    assert CS.crc_table(16, 0x1021, False)[1] == 0x1021
    assert CS.crc_table(8, 0x07, False)[1] == 0x07
    assert CS.crc_table(16, 0x1021, True)[1] == 0x1189


def test_crc_table_found_in_rom():
    nl = emit.Netlist("t")
    nl.m9k.append(rom_block(16, CS.crc_table(16, 0x1021, False)))
    _res, _n = CS.search_m9k(nl, {}, {"c": dict(width=16, poly=0x1021)})
    assert any(h["kind"] == "table-norm" for h in _res["crc_table:c"])
    assert not any(h["kind"] == "table-refl" for h in _res["crc_table:c"])


def test_lfsr_poly_matches_crc_spec():
    nl = fib_netlist(7, [5, 6])
    det = CS.P.detect(nl)
    assert CS.search_crc(det, {"x7": dict(width=7, poly=0x3)})["x7"], "x7+x+1 expected"
    assert not CS.search_crc(det, {"other": dict(width=7, poly=0x9)})["other"]


def test_comparator_polarity_count():
    nl = emit.Netlist("t")
    names = [f"ff_{i}_1_0" for i in range(8)]
    for i, n in enumerate(names):
        nl.ffs.append(ff(i, "1'b0"))
    ones = {1, 4}                                  # constant 0x12 over bits 0..7: bits 1 and 4 set
    # AND of 8 literals as a 2-level tree (two 4-input LUTs, then an AND2)
    def lit_init(pol):
        return 1 << sum(p << i for i, p in enumerate(pol))
    a = and_lut(names[:4], "lc_a_1_0", lit_init([int(i in ones) for i in range(4)]))
    b = and_lut(names[4:], "lc_b_1_0", lit_init([int(i + 4 in ones) for i in range(4)]))
    top = and_lut(["lc_a_1_0", "lc_b_1_0", "1'b1", "1'b1"], "lc_t_1_0", 1 << 0b1111)
    nl.luts += [a, b, top]
    D = CS.P.Design(nl).prepare()
    conj = CS.P.conj_literals(D)
    hit = CS.search_comparators(D, {"c": (bytes([0x12]), 8), "d": (bytes([0x13]), 8)}, conj, [])
    assert [h["sig"] for h in hit["c"]] == ["lc_t_1_0"]
    assert hit["d"] == []                          # popcount differs


def test_crc_specimen_if_present():
    p = os.path.join(REPO, "tmp", "pattern_tests", "crc", "nl.pkl")
    need(p)
    nl = pickle.load(open(p, "rb"))
    res = CS.run(nl, {}, {}, {"c32": dict(width=32, poly=0x04C11DB7), "c16": dict(width=16, poly=0x1021), "c8": dict(width=8, poly=0x07),
                              "c8_other": dict(width=8, poly=0x31)})
    assert [len(res["crc"][k]) for k in ("c32", "c16", "c8", "c8_other")] == [1, 1, 1, 0]
