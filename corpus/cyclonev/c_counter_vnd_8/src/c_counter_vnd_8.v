module c_counter_vnd_8 (clk, q);
  input clk;
  output [7:0] q;
  lpm_counter #(.lpm_width(8), .lpm_direction("UP")) u (.clock(clk), .q(q));
endmodule
