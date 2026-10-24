module top (clk, en, q);
  input clk;
  input en;
  output [3:0] q;
  reg [3:0] q;
  always @(posedge clk) if (en) q <= q + 1'b1;
endmodule
