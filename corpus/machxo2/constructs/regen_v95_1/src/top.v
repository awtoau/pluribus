module top (clk, en, d, q);
  input clk;
  input en;
  input d;
  output q;
  reg q;
  always @(posedge clk) if (en) q <= d;
endmodule
