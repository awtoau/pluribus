module top (clk, a, b, s, y);
  input clk;
  input a;
  input b;
  input s;
  output y;
  reg y;
  always @(posedge clk) y <= s ? b : a;
endmodule
