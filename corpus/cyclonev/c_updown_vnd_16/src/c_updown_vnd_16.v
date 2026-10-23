module c_updown_vnd_16 (clk, up, q);
  input clk, up;
  output [15:0] q;
  lpm_counter #(.lpm_width(16), .lpm_direction("UNUSED")) u (.clock(clk), .updown(up), .q(q));
endmodule
