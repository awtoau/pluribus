module fuzz (
    input wire clk, input wire d0, input wire d1,
    output wire out0, out1, out2, out3
);

wire gnd = 1'b0;
wire q0a, q1a, q0b, q1b;
IDDRXE u0 (.D(d0), .SCLK(clk), .RST(gnd), .Q0(q0a), .Q1(q1a));
IDDRXE u1 (.D(d1), .SCLK(clk), .RST(gnd), .Q0(q0b), .Q1(q1b));
reg [3:0] q;
always @(posedge clk) q <= {q1b, q0b, q1a, q0a};
assign {out3, out2, out1, out0} = q;

endmodule
