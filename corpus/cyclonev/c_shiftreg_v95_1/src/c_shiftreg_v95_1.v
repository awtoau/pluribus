module c_shiftreg_v95_1 (clk, d, q);
  input clk, d;
  output [0:0] q;
  reg [0:0] q;
  always @(posedge clk) q <= d;
endmodule
