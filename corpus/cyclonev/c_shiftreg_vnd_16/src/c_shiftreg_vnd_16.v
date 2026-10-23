module c_shiftreg_vnd_16 (clk, d, q);
  input clk, d;
  output [15:0] q;
  lpm_shiftreg #(.lpm_width(16), .lpm_direction("LEFT")) u (.clock(clk), .shiftin(d), .q(q));
endmodule
