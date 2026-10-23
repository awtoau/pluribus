module c_decoder_vnd_3 (sel, y);
  input [2:0] sel;
  output [7:0] y;
  lpm_decode #(.lpm_width(3), .lpm_decodes(8)) u (.data(sel), .eq(y));
endmodule
