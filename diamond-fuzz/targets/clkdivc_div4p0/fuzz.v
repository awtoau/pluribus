module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire cdivx_w;
CLKDIVC #(.DIV("4.0"), .GSR("ENABLED")) u0 (
    .CLKI(clk), .RST(gnd), .ALIGNWD(gnd), .CDIV1(), .CDIVX(cdivx_w)
);
reg out0_r;
always @(posedge cdivx_w) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
