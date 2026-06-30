module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire dcmout_w;
DCMA u0 (.CLK0(clk), .CLK1(clk), .SEL(gnd), .DCMOUT(dcmout_w));
reg out0_r;
always @(posedge dcmout_w) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
