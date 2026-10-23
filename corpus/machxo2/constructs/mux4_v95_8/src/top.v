module top (clk, a, b, c, d, s, y);
  input clk;
  input [7:0] a;
  input [7:0] b;
  input [7:0] c;
  input [7:0] d;
  input [1:0] s;
  output [7:0] y;
  reg [7:0] y;
  always @(posedge clk) y <= s[1] ? (s[0] ? d : c) : (s[0] ? b : a);
endmodule
