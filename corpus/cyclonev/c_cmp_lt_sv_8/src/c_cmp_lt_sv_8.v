module c_cmp_lt_sv_8 (input logic signed [7:0] a, b, output logic y);
  always_comb y = (a < b);
endmodule
