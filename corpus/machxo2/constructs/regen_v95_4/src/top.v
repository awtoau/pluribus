module top (clk, en, d, q);
  input clk;
  input en;
  input [3:0] d;
  output [3:0] q;
  reg [3:0] q;
  always @(posedge clk) if (en) q <= d;
endmodule
