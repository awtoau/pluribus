module top (clk, a, b, y);
  input clk;
  input a;
  input b;
  output y;
  reg y;
  always @(posedge clk) y <= (a < b);
endmodule
