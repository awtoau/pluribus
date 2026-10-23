module c_shiftreg_vnd_8 (clk, d, q);
  input clk, d;
  output [7:0] q;
  lpm_shiftreg #(.lpm_width(8), .lpm_direction("LEFT")) u (.clock(clk), .shiftin(d), .q(q));
endmodule
