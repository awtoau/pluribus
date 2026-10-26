module adder12(input clk, input [11:0] a, input [11:0] b, output reg [12:0] s);
  always @(posedge clk) s <= a + b;
endmodule
