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


def test_multi_le_tail_strip():
    """A 3-bit adder followed by a 2-LE non-adder tail (a result LUT XORed with an extra flag, then a plain carry buffer): real LE shapes
    from the third-party image's chain #1835 (docs/altera/cycloneIV/cycloneiv-clean-rtl.md multi-LE result tail category, #165).  The
    existing single-LE tail_free only strips LE[-1]; this chain needs both of the last two LEs stripped before the first 3 bits fit ADD."""
    one = "1'b1"
    nl = _chain_nl([(0x0055, ["s0", one, one, one]), (0xA5AF, ["s1", one, "co_0_0_0", one]), (0x5A05, ["s2", one, "co_0_0_1", one]),
                    (0xE10E, ["s3", "flag", "co_0_0_2", one]),       # real tail LE: sum = ~(a^b^c), cout = ~c & (a|b) -- not maj()
                    (0x0F0F, [one, one, "co_0_0_3", one])])          # real collector LE: sum = cout = ~c
    L = rtl.Lift(nl)
    L.index()
    L.chains()
    ch = L.chain_list[0]
    assert ch["ok"] and ch["W"] == 3
    assert ch.get("tail_free") and [t["name"] for t in ch["tail"]] == ["lc_0_0_3", "lc_0_0_4"]
    assert L.tail_free == {"lc_0_0_3", "lc_0_0_4"}
    assert not L.opaque                                             # tail LEs are ordinary logic, not unresolved carry-in


def test_multi_le_tail_chained_carry_out():
    """Regression: a tail_free LE's own co_* can be read by name by the NEXT tail LE (not just by a cone elsewhere).  self.cone only ever
    holds sum outputs, so without need_tail_co the second tail LE's cin reference to the first tail LE's co_* has no declaration -- caught
    by a verilator build of the full image after the multi-LE tail-strip patch (chain #5, real LE shapes, #165)."""
    one = "1'b1"
    nl = _chain_nl([(0x0055, ["s0", one, one, one]), (0xA5AF, ["s1", one, "co_0_0_0", one]), (0x5A05, ["s2", one, "co_0_0_1", one]),
                    (0xE1EF, ["s3", "flag", "co_0_0_2", one]),          # real tail LE 1: result LUT (reads two more real signals)
                    (0xF00F, [one, one, "co_0_0_3", one]),              # real tail LE 2: sum = cin, cout = ~cin (pure buffer/inverter)
                    (0x0F0F, [one, one, "co_0_0_4", one])])             # real collector LE: reads tail LE 2's co_* by name
    L = rtl.Lift(nl)
    L.index()
    L.chains()
    ch = L.chain_list[0]
    assert ch["ok"] and ch.get("tail_free") and len(ch["tail"]) == 3
    fm = {}
    text, rep = rtl.lift(nl, ffmap=fm)
    assert rep["flat_lut_left"] == 2                        # LE 3's sum reduces to a real SOP (not flat); LEs 4/5 are pure carry buffers
    assert "wire co_0_0_3;" in text                         # the bug: co_0_0_3 was read by LE 4's cin pin but never declared
    assert "co_0_0_4 = (16'hF00F >> {1'b0, co_0_0_3," in text   # LE 4's co_* expression reads LE 3's co_* by name, not left dangling


def test_constant_output_pad_and_ffmap():
    one = "1'b1"
    nl = _chain_nl([(0x0055, ["s0", one, one, one]), (0xA5AF, ["s1", one, "co_0_0_0", one]), (0x0F0F, [one, one, "co_0_0_1", one])])
    nl.ios.append(dict(ball="K1", dir="output", drv=None, const=1, oe=None, und=[]))
    nl.ios.append(dict(ball="K2", dir="output", drv=None, const=0, oe=None, und=[]))
    fm = {}
    text, _rep = rtl.lift(nl, ffmap=fm)
    assert "assign io_K1 = 1'b1;" in text and "assign io_K2 = 1'b0;" in text and "UNDECODED: io_K" not in text
    assert set(fm) == {F["name"] for F in nl.ffs} and all("[" in v or v for v in fm.values())
