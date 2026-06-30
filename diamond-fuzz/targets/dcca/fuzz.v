module fuzz (
    input wire clk,
    output wire out0
);

wire vcc = 1'b1;
wire clko_w;
DCCA u0 (.CLKI(clk), .CE(vcc), .CLKO(clko_w));
reg out0_r;
always @(posedge clko_w) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
