module top (clk, rst, d, q);
  input clk;
  input rst;
  input [7:0] d;
  output [7:0] q;
  reg [7:0] q;
  always @(posedge clk or posedge rst) if (rst) q <= 8'd0; else q <= d;
endmodule
