"""Package ball -> site map and the full-class pin score inputs (#168).  Oracle = Quartus build.pin x postfit.vo (check only)."""
import json
import os

import pytest

from conftest import REPO, need
from lifters.cycloneiv_clean import io_decode as ID, io_fields as IF, io_pins as P, pkgpad as K, tracer as T

RB = os.path.join(REPO, "corpus", "cycloneiv", "gx150_rb_078")
CLK_BALLS = {"V11", "W11", "V12", "W12", "V15", "W15", "AJ16", "AK16", "V30", "V29", "T30", "T29", "A15", "B15", "K15", "L15", "K11", "L11", "L10", "M10"}


@pytest.fixture(scope="module")
def pm():
    need(ID.DECODE_PATH, RB)
    io = T.Io()
    return io, P.PinMap(io, IF.Decoder(json.load(open(ID.DECODE_PATH))))


def test_package_pin_counts():
    assert [K.package_pins(d) for d in ("EP4CGX150DF31C7", "EP4CGX150DF27I7", "EP4CGX150CF23C8")] == [896, 672, 484]
    p = K.pins()
    assert K.pin_pad(p) == K.pin_pad_rank(p)
    assert [len(K.pins(n)) for n in (484, 672)] == [484, 672]


def test_clock_pads_all_mapped_once(pm):
    _, m = pm
    s = m.ball_site("EP4CGX150DF31C7")
    clk = {b: v for b, v in s.items() if v[0] in P.CLK_BLOCKS}
    assert set(clk) == CLK_BALLS and len(set(clk.values())) == 20


def test_clock_pad_states_equal_oracle(pm):
    """rb_078 uses 12 clock pads as inputs: those 12 classify used / input, the other 8 unused (mapping evidence, not tuning)."""
    io, m = pm
    from cycloneiv_clean_gate import parse_pin, parse_vo
    ports, _, _ = parse_vo(os.path.join(RB, "postfit.vo"))
    gt = {b for n, (b, _) in parse_pin(os.path.join(RB, "build.pin")).items() if n in ports} & CLK_BALLS
    val, _ = io.cff.read(os.path.join(RB, "bitstream.rbf"))
    c = m.classify(val, "EP4CGX150DF31C7")
    assert len(gt) == 12
    assert {b for b in CLK_BALLS if c[b]["class"] == "used" and c[b]["dir"] == "input"} == gt
    assert {b for b in CLK_BALLS - gt if c[b]["class"] == "unused"} == CLK_BALLS - gt
