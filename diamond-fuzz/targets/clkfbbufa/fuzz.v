module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire vcc = 1'b1;
wire pll_clkop, pll_lock, fb_w;
// CLKFBBUFA: output Z can only connect to EHXPLLJ.CLKFB — no other routing.
// Wire: CLKOP → CLKFBBUFA.A → Z → CLKFB (normal external feedback loop).
// Use FEEDBK_PATH="USERCLOCK" so the PLL accepts an external feedback path.
EHXPLLJ #(
    .CLKOP_DIV(1), .CLKFB_DIV(1), .CLKI_DIV(1),
    .FEEDBK_PATH("USERCLOCK"),
    .CLKOP_ENABLE("ENABLED"),
    .STDBY_ENABLE("DISABLED"),
    .PLL_LOCK_MODE(0)
) u_pll (
    .CLKI(clk), .CLKFB(fb_w),
    .RST(gnd), .STDBY(gnd), .RESETM(gnd), .RESETC(gnd), .RESETD(gnd),
    .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd),
    .PHASESTEP(gnd), .LOADREG(gnd),
    .PLLWAKESYNC(gnd), .ENCLKOP(vcc), .ENCLKOS(gnd), .ENCLKOS2(gnd), .ENCLKOS3(gnd),
    .CLKOP(pll_clkop), .LOCK(pll_lock)
);
CLKFBBUFA u0 (.A(pll_clkop), .Z(fb_w));
reg out0_r;
always @(posedge pll_clkop) out0_r <= pll_lock;
assign out0 = out0_r;

endmodule
