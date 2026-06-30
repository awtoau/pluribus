module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire vcc = 1'b1;
wire clkop_w, clkos_w, clkos2_w, clkos3_w, lock_w;
EHXPLLJ #(
    .CLKI_DIV(1), .CLKFB_DIV(1), .CLKOP_DIV(1),
    .CLKOP_ENABLE("ENABLED"), .CLKOS_ENABLE("ENABLED"),
    .CLKOS2_ENABLE("ENABLED"), .CLKOS3_ENABLE("ENABLED"),
    .FEEDBK_PATH("INT_DIVA"), .FRACN_ENABLE("ENABLED"), .FRACN_DIV(56768)
) u0 (
    .CLKI(clk), .CLKFB(gnd), .RST(gnd), .STDBY(gnd), .PLLWAKESYNC(gnd),
    .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd), .PHASESTEP(gnd), .LOADREG(gnd),
    .RESETM(gnd), .RESETC(gnd), .RESETD(gnd),
    .ENCLKOP(vcc), .ENCLKOS(vcc), .ENCLKOS2(vcc), .ENCLKOS3(vcc),
    .PLLCLK(gnd), .PLLRST(gnd), .PLLSTB(gnd), .PLLWE(gnd),
    .PLLADDR4(gnd), .PLLADDR3(gnd), .PLLADDR2(gnd), .PLLADDR1(gnd), .PLLADDR0(gnd),
    .PLLDATI7(gnd), .PLLDATI6(gnd), .PLLDATI5(gnd), .PLLDATI4(gnd),
    .PLLDATI3(gnd), .PLLDATI2(gnd), .PLLDATI1(gnd), .PLLDATI0(gnd),
    .CLKOP(clkop_w), .CLKOS(clkos_w), .CLKOS2(clkos2_w), .CLKOS3(clkos3_w), .LOCK(lock_w)
);
reg out0_r;
always @(posedge clkop_w) out0_r <= lock_w;
assign out0 = out0_r;

endmodule
