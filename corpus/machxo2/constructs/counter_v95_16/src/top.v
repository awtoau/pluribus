module top (clk, en, q);
  input clk;
  input en;
  output [15:0] q;
  reg [15:0] q;
  always @(posedge clk) if (en) q <= q + 1'b1;
endmodule
