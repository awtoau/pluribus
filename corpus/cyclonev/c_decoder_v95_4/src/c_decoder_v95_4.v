module c_decoder_v95_4 (sel, y);
  input [3:0] sel;
  output [15:0] y;
  assign y = 1 << sel;
endmodule
