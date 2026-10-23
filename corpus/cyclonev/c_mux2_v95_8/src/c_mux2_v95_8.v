module c_mux2_v95_8 (a, b, s, y);
  input [7:0] a, b;
  input s;
  output [7:0] y;
  assign y = s ? b : a;
endmodule
