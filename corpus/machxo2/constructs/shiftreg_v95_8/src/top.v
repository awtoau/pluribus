module top (clk, din, q);
  input clk;
  input din;
  output [7:0] q;
  reg [7:0] q;
  always @(posedge clk) q <= {q[6:0], din};
endmodule
