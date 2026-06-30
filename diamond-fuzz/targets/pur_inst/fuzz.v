module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
PUR #(.RST_PULSE("SYNC")) u0 (.PUR(gnd));
reg out0_r;
always @(posedge clk) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
