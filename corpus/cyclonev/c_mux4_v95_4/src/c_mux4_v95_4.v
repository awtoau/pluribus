module c_mux4_v95_4 (a, b, c, d, s, y);
  input [3:0] a, b, c, d;
  input [1:0] s;
  output [3:0] y;
  assign y = s[1] ? (s[0] ? d : c) : (s[0] ? b : a);
endmodule
