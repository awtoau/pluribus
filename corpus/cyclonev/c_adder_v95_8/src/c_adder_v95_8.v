module c_adder_v95_8 (a, b, s);
  input [7:0] a, b;
  output [8:0] s;
  assign s = {1'b0, a} + {1'b0, b};
endmodule
