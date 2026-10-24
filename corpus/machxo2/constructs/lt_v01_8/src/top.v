module top (
    input [0:0] clk,
    input [7:0] a,
    input [7:0] b,
    output reg [0:0] y
);
  wire signed [7:0] sa = a;
  wire signed [7:0] sb = b;
  always @(posedge clk) y <= (sa < sb);
endmodule
