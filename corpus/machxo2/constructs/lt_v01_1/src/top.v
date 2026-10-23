module top (
    input [0:0] clk,
    input [0:0] a,
    input [0:0] b,
    output reg [0:0] y
);
  wire signed [0:0] sa = a;
  wire signed [0:0] sb = b;
  always @(posedge clk) y <= (sa < sb);
endmodule
