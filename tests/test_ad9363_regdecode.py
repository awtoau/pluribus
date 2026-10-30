"""Hand-made register list -> expected decode (no vendor data)."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ad9363_regdecode", os.path.join(HERE, "..", "scripts", "ad9363_regdecode.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

REGS = """
# addr value
0x002 0xCE   # TX1+TX2, HB2, HB1, FIR x2
0x003 0x8E   # RX2 only
0x004 0x4C   # RX_B + TX_B
0x00A 0x03   # ADC = BBPLL/8
0x044 18     # BBPLL int 18, frac 0 -> 720 MHz at Fref 40 MHz
0x041 0
0x042 0
W 0x043 0
0x045 0
0x005 0x11
0x2AB 0x01
0x2AC 0x8C
0x231 120
0x232 0
0x233 0
0x234 0
0x235 0
0x012 0x02
0x010 0x08
0x013 1
0x0FA 0xE5
0x073 0x18
"""


def rows():
    return {(s, k): v for s, k, v, t in mod.decode(mod.parse(REGS))}


def test_parse_later_wins():
    assert mod.parse("0x10 1\n0x10 2")[0x10] == 2


def test_channels():
    r = rows()
    assert r[("channels", "TX channels enabled")] == "TX1,TX2"
    assert r[("channels", "RX channels enabled")] == "RX2"


def test_ports_and_mode():
    r = rows()
    assert r[("rf-ports", "RX input")] == "RX_B_BALANCED"
    assert r[("rf-ports", "TX output")] == "TX_B"
    assert r[("ensm", "ENSM_MODE")] == "FDD"
    assert r[("data-port", "interface")] == "CMOS"
    assert r[("data-port", "data rate")] == "DDR"


def test_clocks_and_lo():
    r = rows()
    assert r[("clocks", "BBPLL")].startswith("720.0000 MHz")
    assert r[("clocks", "RX sample rate (per channel)")] == "11.2500 MHz"
    assert "LO 2400.0000 MHz" in r[("rf-pll", "RX LO")]


def test_gain():
    r = rows()
    assert r[("gain", "RX1 / RX2 gain control")] == "AGC fast attack / AGC fast attack"
    assert "6.00 dB" in r[("gain", "TX1 atten")]
