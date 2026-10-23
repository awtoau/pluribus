module c_cmp_lt_sv_16 (input logic signed [15:0] a, b, output logic y);
  always_comb y = (a < b);
endmodule
