module c_cmp_eq_sv_16 (input logic [15:0] a, b, output logic y);
  always_comb y = (a == b);
endmodule
