module fuzz (
    input wire clk, input wire pad_in,
    output wire out0
);

wire rx;
IBPU u0 (.I(pad_in), .O(rx));
reg out0_r;
always @(posedge clk) out0_r <= rx;
assign out0 = out0_r;

endmodule
