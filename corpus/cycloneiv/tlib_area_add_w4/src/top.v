module top(input clk, input [3:0] a, input [3:0] b, output [4:0] q);
  reg [4:0] r;
  always @(posedge clk) r <= a + b;
  assign q = r;
endmodule
