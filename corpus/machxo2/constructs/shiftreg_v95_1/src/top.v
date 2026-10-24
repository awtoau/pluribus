module top (clk, din, q);
  input clk;
  input din;
  output q;
  reg q;
  always @(posedge clk) q <= din;
endmodule
