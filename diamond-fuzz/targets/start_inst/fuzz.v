module fuzz (
    input wire clk,
    output wire out0
);

START u0 (.STARTCLK(clk));
reg out0_r;
always @(posedge clk) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
