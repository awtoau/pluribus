module c_decoder_v95_2 (sel, y);
  input [1:0] sel;
  output [3:0] y;
  assign y = 1 << sel;
endmodule
