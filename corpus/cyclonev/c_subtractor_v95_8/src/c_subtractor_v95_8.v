module c_subtractor_v95_8 (a, b, d);
  input [7:0] a, b;
  output [8:0] d;
  assign d = {1'b0, a} - {1'b0, b};
endmodule
