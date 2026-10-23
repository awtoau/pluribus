module c_async_reset_v95_16 (clk, rst, d, q);
  input clk, rst;
  input [15:0] d;
  output [15:0] q;
  reg [15:0] q;
  always @(posedge clk or posedge rst)
    if (rst) q <= 16'd0; else q <= d;
endmodule
