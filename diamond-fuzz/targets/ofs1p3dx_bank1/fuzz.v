module fuzz (
    input wire clk,
    input wire d,
    output wire out0
);

wire gnd = 1'b0;
reg d_r;
always @(posedge clk) d_r <= d;
OFS1P3DX u0 (.D(d_r), .SP(1'b1), .SCLK(clk), .CD(1'b0), .Q(out0));

endmodule
