module fuzz (
    input wire clk, input wire d0, input wire d1,
    output wire out0
);

wire gnd = 1'b0;
wire qw;
ODDRXE u0 (.D0(d0), .D1(d1), .SCLK(clk), .RST(gnd), .Q(qw));
assign out0 = qw;

endmodule
