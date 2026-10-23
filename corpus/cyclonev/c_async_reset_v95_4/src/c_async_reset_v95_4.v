module c_async_reset_v95_4 (clk, rst, d, q);
  input clk, rst;
  input [3:0] d;
  output [3:0] q;
  reg [3:0] q;
  always @(posedge clk or posedge rst)
    if (rst) q <= 4'd0; else q <= d;
endmodule
