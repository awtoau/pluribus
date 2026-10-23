module c_shiftreg_vnd_1 (clk, d, q);
  input clk, d;
  output [0:0] q;
  lpm_shiftreg #(.lpm_width(1), .lpm_direction("LEFT")) u (.clock(clk), .shiftin(d), .q(q));
endmodule
