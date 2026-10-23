module c_cmp_eq_sv_8 (input logic [7:0] a, b, output logic y);
  always_comb y = (a == b);
endmodule
