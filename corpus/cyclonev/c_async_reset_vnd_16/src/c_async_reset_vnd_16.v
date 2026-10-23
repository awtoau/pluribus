module c_async_reset_vnd_16 (clk, rst, d, q);
  input clk, rst;
  input [15:0] d;
  output [15:0] q;
  lpm_ff #(.lpm_width(16)) u (.clock(clk), .aclr(rst), .data(d), .q(q));
endmodule
