module c_adder_v95_1 (a, b, s);
  input [0:0] a, b;
  output [1:0] s;
  assign s = {1'b0, a} + {1'b0, b};
endmodule
