module c_async_reset_vnd_4 (clk, rst, d, q);
  input clk, rst;
  input [3:0] d;
  output [3:0] q;
  lpm_ff #(.lpm_width(4)) u (.clock(clk), .aclr(rst), .data(d), .q(q));
endmodule
