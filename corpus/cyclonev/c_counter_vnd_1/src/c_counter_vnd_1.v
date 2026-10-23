module c_counter_vnd_1 (clk, q);
  input clk;
  output [0:0] q;
  lpm_counter #(.lpm_width(1), .lpm_direction("UP")) u (.clock(clk), .q(q));
endmodule
