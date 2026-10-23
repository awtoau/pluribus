module c_cmp_lt_sv_1 (input logic signed [0:0] a, b, output logic y);
  always_comb y = (a < b);
endmodule
