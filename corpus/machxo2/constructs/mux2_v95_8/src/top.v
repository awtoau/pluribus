module top (clk, a, b, s, y);
  input clk;
  input [7:0] a;
  input [7:0] b;
  input s;
  output [7:0] y;
  reg [7:0] y;
  always @(posedge clk) y <= s ? b : a;
endmodule
