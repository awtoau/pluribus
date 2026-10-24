module top (clk, en, d, q);
  input clk;
  input en;
  input [15:0] d;
  output [15:0] q;
  reg [15:0] q;
  always @(posedge clk) if (en) q <= d;
endmodule
