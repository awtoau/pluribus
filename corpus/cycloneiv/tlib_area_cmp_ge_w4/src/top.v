module top(input clk, input [3:0] a, input [3:0] b, output q);
  reg r;
  always @(posedge clk) r <= (a >= b);
  assign q = r;
endmodule
