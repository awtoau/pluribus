module c_mux2_v95_4 (a, b, s, y);
  input [3:0] a, b;
  input s;
  output [3:0] y;
  assign y = s ? b : a;
endmodule
