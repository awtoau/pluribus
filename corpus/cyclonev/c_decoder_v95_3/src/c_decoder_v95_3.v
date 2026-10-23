module c_decoder_v95_3 (sel, y);
  input [2:0] sel;
  output [7:0] y;
  assign y = 1 << sel;
endmodule
