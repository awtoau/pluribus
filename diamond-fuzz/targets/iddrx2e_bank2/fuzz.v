module fuzz (
    input wire clk, input wire d0,
    output wire out0, out1, out2, out3
);

wire gnd = 1'b0;
wire eclk_w, sclk_w;
wire q0, q1, q2, q3;
ECLKSYNCA u_eclk (.ECLKI(clk), .STOP(gnd), .ECLKO(eclk_w));
CLKDIVC #(.DIV("2.0"), .GSR("ENABLED")) u_div (.CLKI(eclk_w), .RST(gnd), .CDIV1(), .CDIVX(sclk_w));
IDDRX2E u0 (.D(d0), .ECLK(eclk_w), .SCLK(sclk_w), .RST(gnd), .ALIGNWD(gnd), .Q0(q0), .Q1(q1), .Q2(q2), .Q3(q3));
reg [3:0] q;
always @(posedge sclk_w) q <= {q3, q2, q1, q0};
assign {out3, out2, out1, out0} = q;

endmodule
