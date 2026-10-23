module c_cmp_eq_sv_4 (input logic [3:0] a, b, output logic y);
  always_comb y = (a == b);
endmodule
