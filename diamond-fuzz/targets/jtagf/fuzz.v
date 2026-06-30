module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire jce1_w, jshift_w;
JTAGF #(.ER1("ENABLED"), .ER2("DISABLED")) u0 (
    .TCK(), .TMS(), .TDI(), .JTDO1(gnd), .JTDO2(gnd),
    .TDO(), .JTCK(), .JTDI(), .JSHIFT(jshift_w), .JUPDATE(), .JRSTN(),
    .JCE1(jce1_w), .JCE2(), .JRTI1(), .JRTI2()
);
reg out0_r;
always @(posedge clk) out0_r <= jce1_w;
assign out0 = out0_r;

endmodule
