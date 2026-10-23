module c_shiftreg_v95_8 (clk, d, q);
  input clk, d;
  output [7:0] q;
  reg [7:0] q;
  always @(posedge clk) q <= {q[6:0], d};
endmodule
