module c_comb_v95_1 (a, b, c, y);
  input [0:0] a, b, c;
  output [0:0] y;
  assign y = ((a & b) | (~a & c)) ^ (b | c);
endmodule
