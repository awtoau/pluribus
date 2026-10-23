"""PLL divider decode (pll_decode.py).  Words are DIV-1 (Diamond oracle: scripts/pll_oracle.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pll_decode as p  # noqa: E402

CFG = """.tile PT1:GPLL_L0
word: CLKFB_DIV 0001001
word: CLKOP_DIV 0000001
word: CLKOS2_DIV 0000111
word: CLKOS3_DIV 0000001
word: CLKOS_DIV 0000011
enum: CLKOP_ENABLE ENABLED
enum: CLKOS2_ENABLE ENABLED
enum: CLKOS3_ENABLE ENABLED
enum: CLKOS_ENABLE ENABLED
enum: FEEDBK_PATH INT_DIVD
enum: MODE EHXPLLJ

.tile PT2:PIC_T0
enum: PIOA.DRIVE 8
"""


def test_dividers():
    x = p.parse_pll(CFG)
    assert (x["i_div"], x["fb_div"]) == (1, 10)         # absent CLKI_DIV word = 1
    assert x["out_div"] == {"CLKOP": 2, "CLKOS": 4, "CLKOS2": 8, "CLKOS3": 2}
    assert x["fvco_ratio"] == 10.0


def test_output_freqs_and_fin():
    x = p.parse_pll(CFG)
    assert p.output_freqs(x, 50.0) == {"CLKOP": 250.0, "CLKOS": 125.0,
                                       "CLKOS2": 62.5, "CLKOS3": 250.0}
    assert p.solve_fin(x, [62.5, 125.0, 250.0]) == 50.0


def test_unreachable_rates_give_none():
    assert p.solve_fin(p.parse_pll(CFG), [62.5, 125.0, 333.0]) is None


def test_non_intdivd_feedback_is_not_guessed():
    x = p.parse_pll(CFG.replace("INT_DIVD", "CLKOP"))
    assert x["fvco_ratio"] is None
    assert p.output_freqs(x, 50.0) == {}


def test_no_pll():
    assert p.parse_pll(".tile PT2:PIC_T0\nenum: PIOA.DRIVE 8\n") is None
