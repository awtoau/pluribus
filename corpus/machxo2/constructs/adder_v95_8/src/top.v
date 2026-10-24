module top (clk, a, b, y);
  input clk;
  input [7:0] a;
  input [7:0] b;
  output [8:0] y;
  reg [8:0] y;
  always @(posedge clk) y <= {1'b0, a} + {1'b0, b};
endmodule
