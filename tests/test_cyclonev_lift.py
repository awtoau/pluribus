"""Cyclone V lifter: LUT mapping and register-control rules (docs/altera/cycloneV/cyclonev-postfit-oracle.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lifters.cyclonev_lift import CVNode, _complement_inputs, _ff_controls, _lut_table, _port_pins  # noqa: E402

ALL = dict.fromkeys("abcdef", True)


def test_lut_table_counter_q2():
    # counter_en_aclr q[2]~2: Quartus lut_mask 0000FFFF0505FAFA, T half D_F, inputs a c e f only.
    raw = 0x03030302_00000001
    active = dict.fromkeys("abcdef", False) | dict(a=True, c=True, e=True, f=True)
    tt = _lut_table(raw, "T", "D_F", False, active)
    want = 0x0000FFFF0505FAFA
    for v in range(64):
        if v & 0b001010:           # b, d unused
            continue
        assert (tt >> v) & 1 == (want >> v) & 1, v


def test_lut_table_independent_of_inactive_inputs():
    tt = _lut_table(0x123456789ABCDEF0, "B", "C_E", False, dict(ALL, b=False, d=False))
    for v in range(64):
        assert (tt >> v) & 1 == (tt >> (v & ~0b001010)) & 1


def test_complement_inputs_casemux():
    # c_casemux_v95_4 Mux3~0 wiring: ports a,b,c,e,f = !s1,!a0,!c0,!s0,!b0; y = s==0 ? a0 : s==1 ? b0 : s==2 ? c0 : 0
    q = 0
    for v in range(64):                               # Quartus-convention mask from the source function
        a, b, c, e, f = (1 - ((v >> k) & 1) for k in (0, 1, 2, 4, 5))   # port value = !net
        s1, a0, c0, s0, b0 = a, b, c, e, f
        y = [a0, b0, c0, 0][s1 << 1 | s0]
        q |= y << v
    tt = _complement_inputs(q, 0b110111)
    for v in range(64):
        s1, a0, c0, s0, b0 = ((v >> k) & 1 for k in (0, 1, 2, 4, 5))
        assert (tt >> v) & 1 == [a0, b0, c0, 0][s1 << 1 | s0], v


def test_port_pins_modes():
    assert _port_pins("T", "D_E") == dict(a="A", b="B", c="C", d="D", e="E0", f="F0")
    assert _port_pins("B", "C_E") == dict(a="A", b="B", c="D", d="C", e="E1", f="F1")
    assert _port_pins("T", "E_0")["d"] == "E0" and _port_pins("T", "E_0")["e"] == "0"
    assert _port_pins("B", "F_1")["d"] == "FB" and _port_pins("B", "F_1")["e"] == "1"
    assert _port_pins("T", "D_F")["e"] == "FB"


def test_ff_controls_clock_pair_crossing_and_edge():
    kv = {("BCLK_SEL", 3): "CLK1", ("CLK1_INV", None): "1", ("CLK1_SEL", None): "CLKB",
          ("EN1_EN", None): "0", ("ACLR0_SEL", None): "ACLR0", ("TSCLR_DIS", 3): "1",
          ("BSCLR_DIS", 3): "1"}
    # BCLK_SEL names the pair {T1, B0}
    for h, slot in (("T", 1), ("B", 0)):
        ctl = _ff_controls("LAB", ("LAB", 5, 6), kv, 3, h, slot, True, set())
        assert ctl["clk"] == ("node", CVNode("LAB", 5, 6, None, "CLKIN", 1), True)
        assert ctl["ena"] == ("const", 1) and ctl["clrn"] == ("const", 1)
        assert ctl["sclr"] == ("const", 0) and ctl["sload"] == ("const", 0)
        assert ctl["d"] == ("lut", (5, 6, 3, h))
    assert "clk" not in _ff_controls("LAB", ("LAB", 5, 6), kv, 3, "T", 0, True, set())


def test_ff_controls_pin_fed_d_uses_crossed_f_pin():
    pin = CVNode("LAB", 1, 2, 4, "F1", None)
    ctl = _ff_controls("LAB", ("LAB", 1, 2), {("TEF_SEL", 4): "F"}, 4, "T", 0, False, {pin})
    assert ctl["d"] == ("node", pin, False) and ctl["sload"] == ("const", 1)
