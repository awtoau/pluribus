module top (clk, din, q);
  input clk;
  input din;
  output [3:0] q;
  reg [3:0] q;
  always @(posedge clk) q <= {q[2:0], din};
endmodule
