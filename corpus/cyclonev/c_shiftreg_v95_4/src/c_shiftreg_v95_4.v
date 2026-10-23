module c_shiftreg_v95_4 (clk, d, q);
  input clk, d;
  output [3:0] q;
  reg [3:0] q;
  always @(posedge clk) q <= {q[2:0], d};
endmodule
