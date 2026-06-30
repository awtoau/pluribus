module fuzz (
    input wire clk, input wire pad_p, input wire pad_n,
    output wire out0
);

wire rx;
ILVDS u0 (.A(pad_p), .AN(pad_n), .Z(rx));
reg out0_r;
always @(posedge clk) out0_r <= rx;
assign out0 = out0_r;

endmodule
