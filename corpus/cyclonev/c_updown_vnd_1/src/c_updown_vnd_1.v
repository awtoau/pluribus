module c_updown_vnd_1 (clk, up, q);
  input clk, up;
  output [0:0] q;
  lpm_counter #(.lpm_width(1), .lpm_direction("UNUSED")) u (.clock(clk), .updown(up), .q(q));
endmodule
