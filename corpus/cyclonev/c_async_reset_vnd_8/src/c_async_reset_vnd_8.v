module c_async_reset_vnd_8 (clk, rst, d, q);
  input clk, rst;
  input [7:0] d;
  output [7:0] q;
  lpm_ff #(.lpm_width(8)) u (.clock(clk), .aclr(rst), .data(d), .q(q));
endmodule
