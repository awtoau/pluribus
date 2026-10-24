module top (clk, a, b, c, d, s, y);
  input clk;
  input a;
  input b;
  input c;
  input d;
  input [1:0] s;
  output y;
  reg y;
  always @(posedge clk) y <= s[1] ? (s[0] ? d : c) : (s[0] ? b : a);
endmodule
