module c_counter_vnd_4 (clk, q);
  input clk;
  output [3:0] q;
  lpm_counter #(.lpm_width(4), .lpm_direction("UP")) u (.clock(clk), .q(q));
endmodule
