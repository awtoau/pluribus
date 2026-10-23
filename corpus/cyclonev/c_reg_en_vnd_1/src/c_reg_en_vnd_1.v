module c_reg_en_vnd_1 (clk, en, d, q);
  input clk, en;
  input [0:0] d;
  output [0:0] q;
  lpm_ff #(.lpm_width(1)) u (.clock(clk), .enable(en), .data(d), .q(q));
endmodule
