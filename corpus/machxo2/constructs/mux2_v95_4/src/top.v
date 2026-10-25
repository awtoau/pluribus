module top (clk, a, b, s, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  input s;
  output [3:0] y;
  reg [3:0] y;
  always @(posedge clk) y <= s ? b : a;
endmodule
