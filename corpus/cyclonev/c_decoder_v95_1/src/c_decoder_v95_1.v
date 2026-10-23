module c_decoder_v95_1 (sel, y);
  input [0:0] sel;
  output [1:0] y;
  assign y = 1 << sel;
endmodule
