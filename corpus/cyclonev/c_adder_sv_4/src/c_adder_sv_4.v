module c_adder_sv_4 (input logic signed [3:0] a, b, output logic signed [4:0] s);
  always_comb s = a + b;
endmodule
