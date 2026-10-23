module c_sync_reset_v95_1 (clk, rst, d, q);
  input clk, rst;
  input [0:0] d;
  output [0:0] q;
  reg [0:0] q;
  always @(posedge clk) if (rst) q <= 1'd0; else q <= d;
endmodule
