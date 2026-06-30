module fuzz (
    input wire clk, input wire d0, inout wire bidir,
    output wire out0
);

wire gnd = 1'b0;
wire rx;
BBW u0 (.I(d0), .T(gnd), .O(rx), .B(bidir));
reg out0_r;
always @(posedge clk) out0_r <= rx;
assign out0 = out0_r;

endmodule
