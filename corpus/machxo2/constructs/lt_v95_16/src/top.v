module top (clk, a, b, y);
  input clk;
  input [15:0] a;
  input [15:0] b;
  output y;
  reg y;
  always @(posedge clk) y <= (a < b);
endmodule
