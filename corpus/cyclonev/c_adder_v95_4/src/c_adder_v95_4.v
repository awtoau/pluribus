module c_adder_v95_4 (a, b, s);
  input [3:0] a, b;
  output [4:0] s;
  assign s = {1'b0, a} + {1'b0, b};
endmodule
