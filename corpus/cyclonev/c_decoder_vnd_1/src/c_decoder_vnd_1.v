module c_decoder_vnd_1 (sel, y);
  input [0:0] sel;
  output [1:0] y;
  lpm_decode #(.lpm_width(1), .lpm_decodes(2)) u (.data(sel), .eq(y));
endmodule
