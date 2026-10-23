module c_mux2_v95_1 (a, b, s, y);
  input [0:0] a, b;
  input s;
  output [0:0] y;
  assign y = s ? b : a;
endmodule
