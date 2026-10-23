module c_shiftreg_vnd_4 (clk, d, q);
  input clk, d;
  output [3:0] q;
  lpm_shiftreg #(.lpm_width(4), .lpm_direction("LEFT")) u (.clock(clk), .shiftin(d), .q(q));
endmodule
