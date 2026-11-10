"""scripts/cycloneiv_clean_m9k_we_check.py parsers + verdicts on synthetic postfit.vo / routing.rcf snippets (no Quartus / corpus needed)."""
import os
import sys

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_m9k_we_check as W  # noqa: E402

VO = """// Location: M9K_X23_Y40_N0
cycloneiv_ram_block \\ram|auto_generated|ram_block1a0 (
\t.portawe(!\\wea~input_o ),
\t.portare(vcc),
\t.portbwe(\\web~input_o ),
\t.clk0(clk));
// synopsys translate_off
defparam \\ram|auto_generated|ram_block1a0 .operation_mode = "bidir_dual_port";
// Location: M9K_X65_Y7_N0
cycloneiv_ram_block \\r2 (
\t.portawe(gnd),
\t.portbwe(gnd),
\t.clk0(clk));
defparam \\r2 .operation_mode = "rom";
"""

RCF = """signal_name = stim0[15] {
\tLOCAL_INTERCONNECT:X65Y7S0I22;
\tM4K_LEFT_CONTROL_INPUT:X65Y7S0I9;
\tdest = ( altsyncram:ram1|altsyncram_hmo1:auto_generated|ram_block1a0, PORTAWE );
}
signal_name = b {
\tLOCAL_INTERCONNECT:X65Y7S0I66;
\tM4K_LEFT_CONTROL_INPUT:X65Y7S0I11;
\tdest = ( altsyncram:ram1|altsyncram_hmo1:auto_generated|ram_block1a0, PORTBWE );
}
"""


def test_parse_vo():
    r = W.parse_vo(VO)
    assert [(x["xy"], x["mode"], x["portawe"], x["portbwe"]) for x in r] == [
        ((23, 40), "bidir_dual_port", "!\\wea~input_o", "\\web~input_o"), ((65, 7), "rom", "gnd", "gnd")]


def test_parse_rcf():
    assert W.parse_rcf(RCF) == {(65, 7, "A"): (9, 22), (65, 7, "B"): (11, 66)}


def test_classes():
    assert [W.classify_gt(e) for e in ("gnd", "vcc", "!\\a~input_o", "stim0[1]")] == ["gnd", "vcc", "inv", "routed"]
    assert [W.classify_dec(e) for e in ("1'b1", "1'b0", "(!sig)", "sig")] == ["vcc", "gnd", "inv", "routed"]


def test_verdicts():
    assert W.verdict("inv", "inv") == "matched"
    assert W.verdict("inv", "routed") == "wrong"
    assert W.verdict("routed", "gnd") == "missing"
    assert W.verdict("inv", None) == "missing"
    assert W.verdict("gnd", "routed") == "extra"
    assert W.verdict("gnd", "vcc") == "wrong"


def test_parse_vo_instantiated_name():
    vo = "// Location: M9K_X23_Y40_N0\ncycloneiv_ram_block ram(\n\t.portawe(we),\n\t.portbwe(gnd),\n\t.clk0(c));\ndefparam ram.operation_mode = \"single_port\";\n"
    assert W.parse_vo(vo) == [dict(xy=(23, 40), name="ram", mode="single_port", portawe="we", portbwe="gnd")]
