module top(input clk, input sel, input [3:0] a, input [3:0] b, output [3:0] q);
  reg [3:0] r;
  always @(posedge clk) r <= sel ? a : b;
  assign q = r;
endmodule
