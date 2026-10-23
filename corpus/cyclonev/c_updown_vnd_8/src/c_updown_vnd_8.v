module c_updown_vnd_8 (clk, up, q);
  input clk, up;
  output [7:0] q;
  lpm_counter #(.lpm_width(8), .lpm_direction("UNUSED")) u (.clock(clk), .updown(up), .q(q));
endmodule
