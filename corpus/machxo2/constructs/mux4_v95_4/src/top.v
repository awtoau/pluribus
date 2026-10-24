module top (clk, a, b, c, d, s, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  input [3:0] c;
  input [3:0] d;
  input [1:0] s;
  output [3:0] y;
  reg [3:0] y;
  always @(posedge clk) y <= s[1] ? (s[0] ? d : c) : (s[0] ? b : a);
endmodule
