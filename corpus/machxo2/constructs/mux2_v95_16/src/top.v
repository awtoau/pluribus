module top (clk, a, b, s, y);
  input clk;
  input [15:0] a;
  input [15:0] b;
  input s;
  output [15:0] y;
  reg [15:0] y;
  always @(posedge clk) y <= s ? b : a;
endmodule
