module c_reg_en_vnd_16 (clk, en, d, q);
  input clk, en;
  input [15:0] d;
  output [15:0] q;
  lpm_ff #(.lpm_width(16)) u (.clock(clk), .enable(en), .data(d), .q(q));
endmodule
