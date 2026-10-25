module top (clk, en, d, q);
  input clk;
  input en;
  input [7:0] d;
  output [7:0] q;
  reg [7:0] q;
  always @(posedge clk) if (en) q <= d;
endmodule
