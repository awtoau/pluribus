module c_subtractor_v95_1 (a, b, d);
  input [0:0] a, b;
  output [1:0] d;
  assign d = {1'b0, a} - {1'b0, b};
endmodule
