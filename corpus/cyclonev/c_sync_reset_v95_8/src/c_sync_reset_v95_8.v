module c_sync_reset_v95_8 (clk, rst, d, q);
  input clk, rst;
  input [7:0] d;
  output [7:0] q;
  reg [7:0] q;
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
endmodule
