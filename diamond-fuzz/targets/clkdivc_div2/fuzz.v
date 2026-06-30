module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire cdiv1_w, cdivx_w;
CLKDIVC #(.DIV("2.0"), .GSR("ENABLED")) u0 (.RST(gnd), .CLKI(clk), .ALIGNWD(gnd), .CDIV1(cdiv1_w), .CDIVX(cdivx_w));
reg out0_r;
always @(posedge cdivx_w) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
