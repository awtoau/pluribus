module top (clk, rst, d, q);
  input clk;
  input rst;
  input d;
  output q;
  reg q;
  always @(posedge clk) if (rst) q <= 1'd0; else q <= d;
endmodule
