module c_counter_vnd_16 (clk, q);
  input clk;
  output [15:0] q;
  lpm_counter #(.lpm_width(16), .lpm_direction("UP")) u (.clock(clk), .q(q));
endmodule
