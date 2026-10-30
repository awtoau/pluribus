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


def _chain_nl(spec):
    """Fake netlist: spec = [(init, pins)] in chain order (first LE datac, others cin); each sum feeds a live FF."""
    import types
    luts, ffs, ios = [], [], []
    for i, (init, pins) in enumerate(spec):
        luts.append(dict(name=f"lc_0_0_{i}", x=0, y=0, le=i, init=init, pins=list(pins), mode="datac" if i == 0 else "cin",
                         cin=None if i == 0 else f"co_0_0_{i - 1}"))
        ffs.append(dict(name=f"ff_0_0_{i}", x=0, y=0, le=i, d=f"lc_0_0_{i}", clk="clk", ena=None, aclr=None, sclr=None, sload=None, asdata=None))
        ios.append(dict(ball=f"P{i}", dir="output", drv=f"ff_0_0_{i}", oe=None))
    return types.SimpleNamespace(luts=luts, ffs=ffs, ios=ios, srcs={}, m9k=[], mac=[], pll=[], und={}, label="t")


def test_negate_chain_is_mixed_polarity():
    one = "1'b1"
    nl = _chain_nl([(0x0055, ["s0", one, one, one]), (0xA5AF, ["s1", one, "co_0_0_0", one]), (0x5A05, ["s2", one, "co_0_0_1", one]),
                    (0x0F0F, [one, one, "co_0_0_2", one])])
    L = rtl.Lift(nl)
    L.index()
    L.chains()
    ch = L.chain_list[0]
    assert ch["ok"] and ch["mixed"]
    assert not L.opaque


def test_dead_flop_sum_is_not_read():
    one = "1'b1"
    nl = _chain_nl([(0x0055, ["s0", one, one, one]), (0xA5AF, ["s1", one, "co_0_0_0", one]), (0x0F0F, [one, one, "co_0_0_1", one])])
    nl.ios = []                                          # no reader of any flop output
    L = rtl.Lift(nl)
    L.index()
    assert L.unread("lc_0_0_1") and L.unread("lc_0_0_0")
