module c_subtractor_v95_16 (a, b, d);
  input [15:0] a, b;
  output [16:0] d;
  assign d = {1'b0, a} - {1'b0, b};
endmodule
