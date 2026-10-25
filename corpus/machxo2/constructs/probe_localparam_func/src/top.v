module top (input clk, input [3:0] a, output reg [3:0] q);
  function [3:0] inv(input [3:0] x); inv = ~x; endfunction
  always @(posedge clk) q <= inv(a);
endmodule
