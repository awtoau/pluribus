module mult18x18(input clk, input signed [17:0] a, input signed [17:0] b,
  output reg signed [35:0] p);
  always @(posedge clk) p <= a * b;
endmodule
