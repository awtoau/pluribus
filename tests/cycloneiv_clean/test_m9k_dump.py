"""M9K content dump (scripts/cycloneiv_clean_m9k_dump.py, #169): layout round trip, MIF / mem_init sources, specimen words vs source (skip when local data is missing)."""
import importlib.util
import os
import re

import numpy as np
import pytest

from _hb import score_module
from conftest import REPO, report


def _dump():
    spec = importlib.util.spec_from_file_location("m9k_dump", os.path.join(REPO, "scripts", "cycloneiv_clean_m9k_dump.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_candidates_round_trip_every_width():
    from lifters.cycloneiv_clean import m9k
    d = _dump()
    rng = np.random.default_rng(1)
    for w in m9k.WIDTHS:
        words = rng.integers(0, 2, (m9k.depth(w), w), dtype=np.uint8)
        wd, bt = np.divmod(np.arange(m9k.depth(w) * w), w)
        bv = np.zeros(m9k.CONTENT_BITS, np.uint8)
        bv[m9k.pos_of_index(m9k.index(w, wd, bt))] = words.reshape(-1)
        got, outside = d.candidates(bv)[w]
        assert (got == words).all() and outside == 0
    assert d.matrix(bv).shape == (256, 36)


def test_parse_mif_and_score_words(tmp_path):
    d = _dump()
    p = tmp_path / "a.mif"
    p.write_text("WIDTH=8;\nDEPTH=16;\nADDRESS_RADIX=HEX;\nDATA_RADIX=BIN;\nCONTENT BEGIN\n[0..F] : 00000000;\n3 : 10100101;\n[A..B] : 11110000;\nEND;\n")
    w = d.parse_mif(str(p), 8, 16)
    assert w[3] == 0xA5 and w[10] == w[11] == 0xF0 and sum(1 for v in w if v) == 3
    assert d.score_words([1, 0, 2, 3], [1, 5, 0, 4]) == dict(matched=1, missing=1, extra=1, wrong=1)


def test_structure_flags_data_outside_layout():
    d = _dump()
    words = np.zeros((512, 16), np.uint8)
    words[:, 3] = 1
    s = d.structure(words, outside=0, wire={"address_bits_wired": list(range(9)), "routed_output_pins": [3], "packed_mode": 0})
    assert d.consistent(s) and s["empty_columns"] == 15
    s2 = d.structure(words, outside=0, wire={"address_bits_wired": list(range(9)), "routed_output_pins": [5], "packed_mode": 0})
    assert not d.consistent(s2) and s2["nonempty_columns_without_output_pin"] == 1


SPECIMENS = ("gxm9k_hb1_k2", "gxm9k_hb8_k5", "gxm9k_hb9_k1", "gxm9k_hb18_k4", "gxm9k_hb36_k3", "gxm9k_r16_s1", "gxm9k_r9_s1")


def test_specimen_words_equal_source():
    """Words read through the verified layouts equal the source MIF / mem_init words of 7 specimens (all word counts matched, 0 wrong / missing / extra)."""
    score_module(*SPECIMENS)
    from lifters.cycloneiv_clean import asmdb_walk as W, fields as F, m9k, plane as P, sofio
    import sys
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import cycloneiv_clean_dirt as D
    d = _dump()
    try:
        w = W.Walk()
        flds = F.fields(w, D.enum_tables())
        tab = P.load_tables()
    except (sofio.VendorMissing, P.TablesMissing) as e:
        pytest.skip(str(e))
    bases, off = F.bases(w, 39), m9k.content_offsets(flds)
    tot = dict(matched=0, missing=0, extra=0, wrong=0)
    for n in SPECIMENS:
        dd = os.path.join(d.CORPUS, n)
        wd = int(re.match(r"gxm9k_(?:hb|r)(\d+)", n)[1])
        loc = re.search(r"M9K_X(\d+)_Y(\d+)_N0", open(os.path.join(dd, "design.toml")).read())
        inst = m9k.instance(int(loc[1]), int(loc[2]))
        x = sofio.rbf_cram(os.path.join(dd, "bitstream.rbf"))
        r, j, k = np.nonzero(x)
        ones = (r.astype(np.int64) * 800 + j + 1) * 8 + k
        bv = np.isin(m9k.content_cells(bases[inst], off, tab), ones).astype(np.uint8)
        mif = os.path.join(dd, "src", "init.mif")
        want = d.parse_mif(mif, wd, m9k.depth(wd)) if os.path.exists(mif) else d.mem_init_words(os.path.join(dd, "src", "top.v"), wd)
        assert any(want)
        s = d.score_words(d.word_ints(m9k.read_words(bv, wd)), want)
        for q in tot:
            tot[q] += s[q]
    report("m9k_dump_specimen_words", specimens=len(SPECIMENS), **tot)
    assert tot["missing"] == 0 and tot["extra"] == 0 and tot["wrong"] == 0
