module fuzz (
    input wire clk, input wire d0,
    output wire out0
);

wire gnd = 1'b0;
wire qw;
IFS1S1B u0 (
    .D(d0),
    .SCLK(clk),
    .PD(gnd),
    .Q(qw)
);
reg out0_r;
always @(posedge clk) out0_r <= qw;
assign out0 = out0_r;

endmodule
