module c_comb_sv_1 (input logic [0:0] a, b, c, output logic [0:0] y);
  always_comb y = ((a & b) | (~a & c)) ^ (b | c);
endmodule
