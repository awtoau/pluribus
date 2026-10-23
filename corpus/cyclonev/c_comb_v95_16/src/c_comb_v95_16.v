module c_comb_v95_16 (a, b, c, y);
  input [15:0] a, b, c;
  output [15:0] y;
  assign y = ((a & b) | (~a & c)) ^ (b | c);
endmodule
