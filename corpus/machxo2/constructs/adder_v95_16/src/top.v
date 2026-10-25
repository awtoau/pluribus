module top (clk, a, b, y);
  input clk;
  input [15:0] a;
  input [15:0] b;
  output [16:0] y;
  reg [16:0] y;
  always @(posedge clk) y <= {1'b0, a} + {1'b0, b};
endmodule
