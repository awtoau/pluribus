module fuzz (
    input wire clk,
    input wire d,
    output wire out0
);

wire q_w;
TSALL u0 (.TSALL(1'b0));
reg out0_r;
always @(posedge clk) out0_r <= d;
assign out0 = out0_r;

endmodule
