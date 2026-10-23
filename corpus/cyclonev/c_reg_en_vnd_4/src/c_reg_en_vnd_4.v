module c_reg_en_vnd_4 (clk, en, d, q);
  input clk, en;
  input [3:0] d;
  output [3:0] q;
  lpm_ff #(.lpm_width(4)) u (.clock(clk), .enable(en), .data(d), .q(q));
endmodule
