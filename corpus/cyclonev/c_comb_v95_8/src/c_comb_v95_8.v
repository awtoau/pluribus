module c_comb_v95_8 (a, b, c, y);
  input [7:0] a, b, c;
  output [7:0] y;
  assign y = ((a & b) | (~a & c)) ^ (b | c);
endmodule
