module fuzz (
    input wire clk, input wire d0, input wire d1,
    output wire out0
);

wire gnd = 1'b0;
wire eclk_w, sclk_w, qw;
ECLKSYNCA u_eclk (.ECLKI(clk), .STOP(gnd), .ECLKO(eclk_w));
CLKDIVC #(.DIV("4.0"), .GSR("ENABLED")) u_div (.CLKI(eclk_w), .RST(gnd), .CDIV1(), .CDIVX(sclk_w));
ODDRX4B u0 (.D0(d0), .D1(d1), .D2(d0), .D3(d1), .D4(d0), .D5(d1), .D6(d0), .D7(d1),
    .ECLK(eclk_w), .SCLK(sclk_w), .RST(gnd), .Q(qw));
assign out0 = qw;

endmodule
