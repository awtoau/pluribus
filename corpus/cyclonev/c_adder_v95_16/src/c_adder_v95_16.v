module c_adder_v95_16 (a, b, s);
  input [15:0] a, b;
  output [16:0] s;
  assign s = {1'b0, a} + {1'b0, b};
endmodule
