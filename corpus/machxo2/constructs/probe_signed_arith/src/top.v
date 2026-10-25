module top (input clk, input signed [3:0] a, input signed [3:0] b, output reg y);
  always @(posedge clk) y <= a < b;
endmodule
