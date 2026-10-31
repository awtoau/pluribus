module top(input clk, input [7:0] a, input [7:0] b, output [8:0] q);
  reg [8:0] r;
  always @(posedge clk) r <= a - b;
  assign q = r;
endmodule
