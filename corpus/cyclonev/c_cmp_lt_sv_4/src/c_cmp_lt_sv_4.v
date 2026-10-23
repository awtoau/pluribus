module c_cmp_lt_sv_4 (input logic signed [3:0] a, b, output logic y);
  always_comb y = (a < b);
endmodule
