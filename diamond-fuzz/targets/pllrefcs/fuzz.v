module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0, vcc = 1'b1;
wire pllref_out, pll_clkop, pll_lock;
PLLREFCS u_ref (.CLK0(clk), .CLK1(gnd), .SEL(gnd), .PLLCSOUT(pllref_out));
EHXPLLJ #(
    .CLKOP_DIV(1), .CLKFB_DIV(1), .CLKI_DIV(1),
    .FEEDBK_PATH("CLKOP"),
    .CLKOP_ENABLE("ENABLED"),
    .STDBY_ENABLE("DISABLED"),
    .PLL_LOCK_MODE(0)
) u_pll (
    .CLKI(pllref_out), .CLKFB(pll_clkop),
    .RST(gnd), .STDBY(gnd), .RESETM(gnd), .RESETC(gnd), .RESETD(gnd),
    .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd),
    .PHASESTEP(gnd), .LOADREG(gnd),
    .PLLWAKESYNC(gnd), .ENCLKOP(vcc), .ENCLKOS(gnd), .ENCLKOS2(gnd), .ENCLKOS3(gnd),
    .CLKOP(pll_clkop), .LOCK(pll_lock)
);
reg out0_r;
always @(posedge clk) out0_r <= pll_lock;
assign out0 = out0_r;

endmodule
