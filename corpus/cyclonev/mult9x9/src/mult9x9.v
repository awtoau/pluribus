module mult9x9(input clk, input signed [8:0] a, input signed [8:0] b,
  output reg signed [17:0] p);
  always @(posedge clk) p <= a * b;
endmodule
