module c_adder_sv_1 (input logic signed [0:0] a, b, output logic signed [1:0] s);
  always_comb s = a + b;
endmodule
