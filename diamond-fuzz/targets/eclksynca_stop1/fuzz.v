module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire ecsout_w;
ECLKSYNCA u0 (.ECLKI(clk), .STOP(1'b1), .ECLKO(ecsout_w));
reg out0_r;
always @(posedge ecsout_w) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
