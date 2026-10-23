module c_shiftreg_v95_16 (clk, d, q);
  input clk, d;
  output [15:0] q;
  reg [15:0] q;
  always @(posedge clk) q <= {q[14:0], d};
endmodule
