module top (input clk, output reg [3:0] q);
  always @(posedge clk) q++;
endmodule
