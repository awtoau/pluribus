module c_decoder_vnd_2 (sel, y);
  input [1:0] sel;
  output [3:0] y;
  lpm_decode #(.lpm_width(2), .lpm_decodes(4)) u (.data(sel), .eq(y));
endmodule
