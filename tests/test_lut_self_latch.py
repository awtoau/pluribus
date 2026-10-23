"""verilog._lut_self_latch: a 6-input LUT fed by its own output becomes a latch unless it can oscillate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import verilog  # noqa: E402


def _init(fn):
    return "".join(str(fn(i)) for i in range(63, -1, -1))     # MSB-first, f(idx) = init[63 - idx]


def _exprs(**kw):
    e = {ch: "1'b0" for ch in "abcdef"}
    e.update(kw)
    return e


def test_or_hold_is_set_hold_latch():
    blk = verilog._lut_self_latch(_init(lambda i: (i & 1) | ((i >> 1) & 1)), "z", _exprs(a="z", b="s"))
    txt = "\n".join(blk)
    assert "reg _lat_z;" in txt and "always @*" in txt and "assign z = _lat_z;" in txt
    assert "_lat_z_clr = 32'h0;" in txt           # f(0,s=0)=0, f(1,s=0)=1: hold, never clear


def test_inverting_feedback_stays_a_loop():
    assert verilog._lut_self_latch(_init(lambda i: 1 - (i & 1)), "z", _exprs(a="z")) is None


def test_no_self_input_untouched():
    assert verilog._lut_self_latch(_init(lambda i: i & 1), "z", _exprs(a="q")) is None
