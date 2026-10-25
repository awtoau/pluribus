module top (clk, a, b, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  output [4:0] y;
  reg [4:0] y;
  always @(posedge clk) y <= {1'b0, a} + {1'b0, b};
endmodule
