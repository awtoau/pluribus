"""cycloneiv_clean_pad_roles.py (#165): hand-built toy netlist, one pad per structural role + a 4-pad phase-select bus fed from M9K lanes."""
import importlib.util
import os
import types

from conftest import REPO

spec = importlib.util.spec_from_file_location("pad_roles", os.path.join(REPO, "scripts", "cycloneiv_clean_pad_roles.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def lut(name, pins, fn):
    pins = pins + ["1'b0"] * (4 - len(pins))
    init = 0
    for idx in range(16):
        v = [(idx >> b) & 1 for b in range(4)]
        init |= (fn(*v) & 1) << idx
    return dict(name=name, init=init, pins=pins, mode="datac", cin=None)


def build():
    L, F, IO = [], [], []

    def ff(name, d, neg=False, **kw):
        F.append(dict(name=name, d=d, clk="clk", clk_inv=neg, **kw))

    def io(ball, d, drv=None):
        IO.append(dict(ball=ball, site=(5, len(IO)), dir=d, drv=drv, const=None))
    # rx_capture: pad -> buffer LUT -> FF, FF unused
    L.append(lut("lc_rx", ["pad_R"], lambda a, *_: a))
    ff("ff_rx", "lc_rx")
    io("R", "input")
    # nosink input
    io("Z", "input")
    # phase_out bus: P = reg(lut(m9k bit)), N = neg-edge copy of P, pad = mux(sel, P, N)
    for i in range(4):
        q = f"m9k_1_2_q[{i * 9 + 3 * 0 + i % 1}]"
        L.append(lut(f"lc_d{i}", [q, "ff_en"], lambda a, b, *_: a & b))
        ff(f"ff_p{i}", f"lc_d{i}")
        ff(f"ff_n{i}", f"ff_p{i}", neg=True)
        L.append(lut(f"lc_o{i}", [f"ff_p{i}", f"ff_n{i}", "ff_sel"], lambda p, n, s, *_: n if s else p))
        io(f"T{i}", "output", f"lc_o{i}")
    ff("ff_en", "lc_en")
    ff("ff_sel", "lc_en")
    L.append(lut("lc_en", ["ff_en"], lambda a, *_: 1 - a))
    # const output
    io("C", "output")
    # through: input pad forwarded combinationally to an output
    L.append(lut("lc_th", ["pad_X", "ff_en"], lambda a, b, *_: a if b else 0))
    io("X", "input")
    io("Y", "output", "lc_th")
    nl = types.SimpleNamespace(ffs=F, luts=L, ios=IO, m9k=[], mac=[])
    return nl


def test_roles():
    nl = build()
    g, rows, groups = P.run(nl, 2)
    roles = P.classify(g, rows)
    assert roles["R"][0] == "rx_capture"
    assert roles["Z"][0] == "nosink_in"
    assert roles["C"][0] == "const_out"
    assert all(roles[f"T{i}"][0] == "phase_out" for i in range(4))
    assert roles["X"][0] == "through_in" and roles["Y"][0] == "through_out"


def test_group_bus():
    nl = build()
    g, rows, groups = P.run(nl, 2)
    big = [b for b in groups.values() if len(b) >= P.MIN_BUS]
    assert big and sorted(big[0]) == ["T0", "T1", "T2", "T3"]


def test_word_lanes_stride():
    g, rows, groups = P.run(build(), 2)
    roles = P.classify(g, rows)
    lanes, stride = P.word_lanes(g, rows, roles)
    assert set(lanes) == {"T0", "T1", "T2", "T3"} and stride == {}
