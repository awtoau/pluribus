module c_comb_sv_4 (input logic [3:0] a, b, c, output logic [3:0] y);
  always_comb y = ((a & b) | (~a & c)) ^ (b | c);
endmodule
