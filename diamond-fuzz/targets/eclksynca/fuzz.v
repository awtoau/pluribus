module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire eclko_w;
ECLKSYNCA u0 (.ECLKI(clk), .STOP(gnd), .ECLKO(eclko_w));
reg out0_r;
always @(posedge eclko_w) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
