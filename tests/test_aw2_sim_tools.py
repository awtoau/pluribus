"""Text-transform helpers of sim_no_ip.py and aw2_roundtrip.py (no simulator/Diamond needed)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

NETLIST = """module aw2 (input wire a);
    EFB #(
        .EFB_SPI("ENABLED")
    ) efb_inst (
        .WBCLKI(a),
        .WBACKO(b)
    );
endmodule

(* blackbox *)
module EFB #(
    parameter EFB_SPI = "DISABLED"
) (
    input wire WBCLKI
);
endmodule

module efb_spi_slave (
    input wire x
);
endmodule
"""


def test_prep_verilog_drops_stub():
    import aw2_roundtrip as rt
    out = rt.prep_verilog(NETLIST)
    assert "blackbox" not in out and "efb_spi_slave" not in out
    assert ".EFB_SPI(\"ENABLED\")" in out


def test_blackbox_regex_matches_parameterised_stub():
    import sim_no_ip as s
    out, n = s._BLACKBOX_RE.subn("", NETLIST)
    assert n == 1 and "module EFB" not in out and "module aw2" in out


TB = """module aw2_tb;
    reg spec_clk_main = 1'b0;
    reg FPGA_nCS = 1'b0;
    aw2 dut ();
    always #4.0000 spec_clk_main = ~spec_clk_main;  // 125 MHz
    // ADC data: a rolling ramp
    initial begin
        #2000 $finish;   // 2 us
    end
endmodule
"""


def test_build_tb_replaces_clock_and_idles_cs():
    import sim_no_ip as s
    plan = {"fin": 50.0, "drive": {"spec_clk_main": "CLKOP"},
            "pll": {"i_div": 1, "fb_div": 10,
                    "out_div": {"CLKOP": 2, "CLKOS": 4, "CLKOS2": 8, "CLKOS3": 2}}}
    out = s.build_tb(TB, plan, [("WRITE X", [0xA8, 0, 1])], 20000, ["ff_a"], 55)
    assert "reg FPGA_nCS = 1'b1;" in out
    assert "always #4.0000" not in out
    assert "pll_model #(1, 10, 2, 4, 8, 2)" in out
    assert "always @* spec_clk_main = pll_op;" in out
    assert "spi_byte(8'ha8)" in out and 'FF %b ff_a' in out


def test_build_tb_refuses_missing_anchor():
    import sim_no_ip as s
    with pytest.raises(SystemExit):
        s.build_tb(TB.replace("reg FPGA_nCS = 1'b0;", ""), None, [], 1000, [], 55)
