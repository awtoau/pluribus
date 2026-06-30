module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
BCINRD #(.BANKID(0)) u0 (.INRDENI(gnd));
reg out0_r;
always @(posedge clk) out0_r <= gnd;
assign out0 = out0_r;

endmodule
