"""io_line.py / asmdb_select class 20 + std_select: HIO pad data pin selection vs the routing.rcf LOCAL_INTERCONNECT feeding the pad (#165)."""
import glob
import os
import re

import pytest

from conftest import REPO, report

from lifters.cycloneiv_clean import asmdb_select as S


class FakeWalk:
    def __init__(self, muxes):
        self.m = muxes

    def mux(self, ref):
        return self.m[ref]


def test_hetero_select_maps_then_encodes():
    # source: ASMDB_HETEROGENEOUS_ENCODED_MUX::select@0x8c334: value -> map mux entry -> ENCODED_MUX::select (bit k = (v >> k) & 1)
    w = FakeWalk({"a": {"cls": 20, "bits": [10, 11, 12], "bits2": [5, 0, 3]}})
    assert S.select(w, "a", 0) == [(10, 1), (11, 0), (12, 1)]
    assert S.select(w, "a", 2) == [(10, 1), (11, 1), (12, 0)]
    with pytest.raises(ValueError):
        S.select(w, "a", 3)


def test_std_select_chains_next_values_and_inverts():
    # source: ASMDB_ARCH_GROUP_STD::select@0x7a3ac: next value = nxt.m_mux_bits[value]; arch_value 0 inverts the entry
    w = FakeWalk({"e1": {"cls": 15, "bits": [1, 2]}, "e2": {"cls": 15, "bits": [3]}, "n": {"cls": 17, "bits": [1, 0]}})
    g = {"paths": [["e1", "e2"]], "data": [{"av": 1, "nxt": "n"}, {"av": 0, "nxt": None}]}
    assert S.std_select(w, g, 0, 0) == [(1, 0), (2, 0), (3, 0)]       # value 0 -> e1 bits 0,0; next value n[0] = 1 -> e2 bit 1, inverted to 0
    assert S.std_select(w, g, 0, 1) == [(1, 1), (2, 0), (3, 1)]       # value 1 -> next n[1] = 0 -> e2 bit 0, inverted to 1


def _gt_li(design):
    """{(x, y, k): LOCAL_INTERCONNECT index feeding the output pad's data pin} for the HIO output pads of a design (build.pin + routing.rcf)."""
    from lifters.cycloneiv_clean import io_decode as ID, tracer as T
    chain = ID.Chain()
    site_of = {b: s for b, s in chain.ball_site.items() if s}
    pins = {}
    for line in open(os.path.join(design, "build.pin")):
        f = [s.strip() for s in line.split(":")]
        if len(f) >= 3 and f[2] == "output":
            pins[f[0]] = f[1]
    out = {}
    for n in T.parse_rcf(os.path.join(design, "routing.rcf")):
        par = {c: p for p, c in n["edges"]}
        for last, cell, port, _rp in n["dests"]:
            site = site_of.get(pins.get(cell[:-7])) if cell.endswith("~output") and port == "I" else None
            if site is None or site[0] != 5:
                continue
            p = par.get(last)
            if p and p[0] == "LOCAL_INTERCONNECT":
                out[tuple(map(int, re.fullmatch(r"X(\d+)Y(\d+)SUB_LOC(\d+)", chain.site_pad[site][0]).groups()))] = p[4]
    return out


def test_hio_data_line_equals_rcf_li():
    import sys
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import cycloneiv_clean_dirt as D
    from lifters.cycloneiv_clean import asmdb_walk as W, io_line, pkgpad, tracer as T
    ds = [os.path.join(REPO, "corpus", "cycloneiv", f"gx150_rb_{i:03d}") for i in range(10)]
    if not all(os.path.exists(os.path.join(d, "routing.rcf")) for d in ds):
        pytest.skip("corpus missing")
    ln = io_line.Line(W.Walk(), D.enum_tables()["arch_group_type"], 5, "MIO_LABLINE_TO_DATA", 0)
    pads = pkgpad.pads()
    sp = pkgpad.io_site_pads(pads)
    site_of = {pkgpad.pad_site(pads[sp[(5, s)]]): s for s in range(ln.n_sites) if (5, s) in sp}
    ok = bad = 0
    for d in ds:
        bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
        for xyk, li in _gt_li(d).items():
            if ln.select(bits, site_of[xyk]) == li:
                ok += 1
            else:
                bad += 1
    report("io_line_hio_data", matched=ok, other=bad)
    assert ok > 50 and bad == 0
