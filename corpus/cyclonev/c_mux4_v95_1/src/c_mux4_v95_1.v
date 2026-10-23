module c_mux4_v95_1 (a, b, c, d, s, y);
  input [0:0] a, b, c, d;
  input [1:0] s;
  output [0:0] y;
  assign y = s[1] ? (s[0] ? d : c) : (s[0] ? b : a);
endmodule
