module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire ecsout_w;
ECLKBRIDGECS u0 (.CLK0(clk), .CLK1(clk), .SEL(gnd), .ECSOUT(ecsout_w));
reg out0_r;
always @(posedge ecsout_w) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
