module fuzz (
    input wire clk,
    input wire d,
    output wire out0
);

wire q_w;
IFS1P3BX u0 (.D(d), .SP(1'b1), .SCLK(clk), .PD(1'b0), .Q(q_w));
reg out0_r;
always @(posedge clk) out0_r <= q_w;
assign out0 = out0_r;

endmodule
