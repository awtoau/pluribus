"""rtl.py unit tests (#165): exactness of the cone simplifier on generated truth tables (no bitstream needed)."""
import random

from lifters.cycloneiv_clean import rtl


def structural_tt(simple):
    """Truth table of the rendered expression (python bit semantics), over simple[2]."""
    expr, _rule = rtl.render(simple, simple[2])
    k = len(simple[2])
    tt = 0
    for idx in range(1 << k):
        env = {n: (idx >> j) & 1 for j, n in enumerate(simple[2])}
        tt |= (eval(expr.replace("1'b0", "0").replace("1'b1", "1"), {}, env) & 1) << idx
    return tt


def test_simp_exact_random():
    rnd = random.Random(7)                      # fixed seed: reproducible
    for k in range(1, rtl.MAXL + 1):
        for _ in range(40):
            tt = rnd.getrandbits(1 << k)
            leaves = [f"v{j}" for j in range(k)]
            sp = rtl.simp(leaves, tt)
            if sp[0] in ("mux", "tt"):
                continue
            assert structural_tt(sp) == rtl.reduce_tt(leaves, tt)[1]


def test_mux_detected():
    leaves = ["s", "a", "b"]
    tt = 0
    for idx in range(8):
        s, a, b = idx & 1, (idx >> 1) & 1, (idx >> 2) & 1
        tt |= (b if s else a) << idx
    sp = rtl.simp(leaves, tt)
    assert sp[0] == "mux"
    text, rule = rtl.render(sp, sp[2])
    assert rule == "MUX2" and "?" in text


def test_xor_and_const():
    assert rtl.simp(["a", "b", "c"], 0x96)[0] == "xor"
    assert rtl.simp(["a", "b"], 0)[0] == "const"
    assert rtl.simp(["a", "b"], 0b1010)[0] == "lit"
