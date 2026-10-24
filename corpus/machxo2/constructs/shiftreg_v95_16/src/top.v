module top (clk, din, q);
  input clk;
  input din;
  output [15:0] q;
  reg [15:0] q;
  always @(posedge clk) q <= {q[14:0], din};
endmodule
