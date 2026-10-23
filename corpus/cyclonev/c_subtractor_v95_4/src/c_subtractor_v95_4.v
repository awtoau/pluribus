module c_subtractor_v95_4 (a, b, d);
  input [3:0] a, b;
  output [4:0] d;
  assign d = {1'b0, a} - {1'b0, b};
endmodule
