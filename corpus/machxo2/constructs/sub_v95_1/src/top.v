module top (clk, a, b, y);
  input clk;
  input a;
  input b;
  output [1:0] y;
  reg [1:0] y;
  always @(posedge clk) y <= {1'b0, a} - {1'b0, b};
endmodule
