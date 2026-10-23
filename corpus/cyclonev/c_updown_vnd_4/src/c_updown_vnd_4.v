module c_updown_vnd_4 (clk, up, q);
  input clk, up;
  output [3:0] q;
  lpm_counter #(.lpm_width(4), .lpm_direction("UNUSED")) u (.clock(clk), .updown(up), .q(q));
endmodule
