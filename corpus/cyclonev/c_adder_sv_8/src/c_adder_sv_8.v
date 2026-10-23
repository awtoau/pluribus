module c_adder_sv_8 (input logic signed [7:0] a, b, output logic signed [8:0] s);
  always_comb s = a + b;
endmodule
