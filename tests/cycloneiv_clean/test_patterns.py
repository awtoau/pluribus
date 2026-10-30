"""patterns.py (#165): GF(2) algebra, detectors on hand-built netlists, and the Quartus-built specimens (skipped when tmp/pattern_tests/ is absent)."""
import os
import random
import sys

import pytest

from conftest import REPO, report

sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import emit, patterns as P

TESTS = os.path.join(REPO, "tmp", "pattern_tests")


def xor_lut(n, pins, name, inv=False):
    init = 0
    for idx in range(16):
        bits = [(idx >> b) & 1 for b in range(4)]
        v = 0
        for b in range(n):
            v ^= bits[b]
        init |= ((v ^ int(inv)) & 1) << idx
    return dict(name=name, x=1, y=1, le=0, lab=0, init=init, pins=pins + ["1'b0"] * (4 - len(pins)), prod=[None] * 4, rec=[None] * 4, cin=None, mode="datac")


def ff(i, d, clk="clk0", **kw):
    return dict(name=f"ff_{i}_1_0", x=i, y=1, le=0, lab=0, d=d, clk=clk, und=[], **kw)


def fib_netlist(n, taps):
    """Fibonacci LFSR: stage 0 = XOR of stages in taps, stage i = stage i-1; pad-free, autonomous."""
    nl = emit.Netlist("t")
    names = [f"ff_{i}_1_0" for i in range(n)]
    nl.luts.append(dict(xor_lut(len(taps), [names[t] for t in taps], "lc_100_1_0", inv=True)))
    nl.ffs.append(ff(0, "lc_100_1_0"))
    for i in range(1, n):
        buf = dict(name=f"lc_{i}_9_0", x=i, y=9, le=0, lab=0, init=0xAAAA, pins=[names[i - 1], "1'b0", "1'b0", "1'b0"], prod=[None] * 4, rec=[None] * 4, cin=None,
                   mode="datac")
        nl.luts.append(buf)
        nl.ffs.append(ff(i, buf["name"]))
    return nl


def test_charpoly_companion():
    for exps in ((7, 6, 0), (15, 14, 0), (32, 26, 23, 22, 16, 12, 11, 10, 8, 7, 5, 4, 2, 1, 0)):
        p = P.poly_of(exps)
        assert P.charpoly(P.companion(p)) == p


def test_charpoly_is_similarity_invariant():
    rnd = random.Random(3)
    p = P.poly_of((9, 5, 0))
    n = 9
    perm = list(range(n))
    rnd.shuffle(perm)
    m = P.companion(p)
    pm = [sum(((m[perm[i]] >> perm[j]) & 1) << j for j in range(n)) for i in range(n)]
    assert P.charpoly(pm) == p


def test_known_match_and_primitive():
    assert P.is_primitive(P.poly_of((15, 14, 0))) is True
    assert P.is_primitive(P.poly_of((8, 4, 3, 2, 0))) is True
    hits = P.match_known(P.poly_of((15, 14, 0)), 15)
    assert any(name.startswith("x15+x14+1") for name, _o in hits)


def test_gf_matrix_canon_is_permutation_invariant():
    rows = P.gf_mul_matrix(0x57, 0x11D)
    rnd = random.Random(5)
    cp, rp = list(range(8)), list(range(8))
    rnd.shuffle(cp)
    rnd.shuffle(rp)
    perm = [sum(((rows[rp[i]] >> cp[j]) & 1) << j for j in range(8)) for i in range(8)]
    assert P.canon(perm, 8) == P.canon(rows, 8)
    assert (0x11D, 0x57) in P.gf_table()[P.canon(perm, 8)]


def test_fibonacci_detected_on_handbuilt_netlist():
    nl = fib_netlist(7, [5, 6])
    res = P.detect(nl)
    assert len(res["lfsr"]) == 1
    g = res["lfsr"][0]
    assert g["n"] == 7 and g["form"] == "fibonacci" and g["autonomous"] and g["rank"] == 7
    assert g["match"] and g["match"][0][0].startswith("PRBS7")


def test_no_lfsr_without_feedback():
    nl = fib_netlist(7, [5, 6])
    nl.ffs[0]["d"] = "1'b0"                          # feedback cut: a shift register, not an LFSR
    res = P.detect(nl)
    assert res["lfsr"] == [] and res["parallel"] == []


@pytest.mark.parametrize("name", ["lfsr", "crc", "conv", "descr", "gfmul", "misc", "fifoish"])
def test_specimen_scores_clean(name):
    rbf = os.path.join(TESTS, name, "bitstream.rbf")
    if not os.path.exists(rbf):
        pytest.skip(f"local specimen missing: tmp/pattern_tests/{name}")
    import cycloneiv_pattern_score as S
    nl = S.netlist(emit.Ctx(), rbf, name, os.path.join(TESTS, name, "nl.pkl"))
    sc = S.score_specimen(name, P.detect(nl))
    report(f"patterns_specimen_{name}", **sc)
    for cls, t in sc.items():
        assert t["missing"] == 0 and t["extra"] == 0 and t["wrong"] == 0, (name, cls, t)
