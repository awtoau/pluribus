module top (clk, en, q);
  input clk;
  input en;
  output q;
  reg q;
  always @(posedge clk) if (en) q <= q + 1'b1;
endmodule
