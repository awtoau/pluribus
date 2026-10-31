module top(input clk, input [7:0] a, input [7:0] b, output q);
  reg r;
  always @(posedge clk) r <= (a >= b);
  assign q = r;
endmodule
