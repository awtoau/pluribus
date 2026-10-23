module c_reg_en_vnd_8 (clk, en, d, q);
  input clk, en;
  input [7:0] d;
  output [7:0] q;
  lpm_ff #(.lpm_width(8)) u (.clock(clk), .enable(en), .data(d), .q(q));
endmodule
