module c_mux2_v95_16 (a, b, s, y);
  input [15:0] a, b;
  input s;
  output [15:0] y;
  assign y = s ? b : a;
endmodule
