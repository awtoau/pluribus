module c_decoder_vnd_4 (sel, y);
  input [3:0] sel;
  output [15:0] y;
  lpm_decode #(.lpm_width(4), .lpm_decodes(16)) u (.data(sel), .eq(y));
endmodule
