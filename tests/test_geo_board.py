"""Board pin-name loader (scripts/geo_devices/common.py load_board) against a synthetic fixture."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from geo_devices import common  # noqa: E402

FIX = REPO / "tests/fixtures/geo_board"


def test_names_signal_net():
    pins, src = common.load_board(FIX, "TQFP32")
    assert src["file"] == "pins.tsv" and src["cols"][5] == "label"
    assert pins["1"]["name"] == "CLK_IN" and pins["1"]["sig"] == "U1.CLK" and pins["1"]["net"] == "n_clk" and pins["1"]["dir"] == "in"
    assert pins["1"]["names"] == ["CLK_IN", "U1.CLK", "n_clk"]
    assert pins["4"]["name"] == "DATA0" and pins["4"]["desc"] == "data line"


def test_unnamed_pins_have_no_name():
    pins, _ = common.load_board(FIX, "TQFP32")
    assert pins["2"]["name"] == "" and pins["2"]["names"] == ["n_out"]      # '?' label -> no name, net kept
    assert pins["3"]["name"] == "" and pins["3"]["names"] == []             # generic 'pin3' -> no name


def test_other_package_gives_nothing():
    assert common.load_board(FIX, "TQFP100") == ({}, None)
