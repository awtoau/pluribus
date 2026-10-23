module c_comb_v95_4 (a, b, c, y);
  input [3:0] a, b, c;
  output [3:0] y;
  assign y = ((a & b) | (~a & c)) ^ (b | c);
endmodule
