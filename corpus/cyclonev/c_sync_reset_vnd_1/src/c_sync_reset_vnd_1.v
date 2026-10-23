module c_sync_reset_vnd_1 (clk, rst, d, q);
  input clk, rst;
  input [0:0] d;
  output [0:0] q;
  lpm_ff #(.lpm_width(1)) u (.clock(clk), .sclr(rst), .data(d), .q(q));
endmodule
