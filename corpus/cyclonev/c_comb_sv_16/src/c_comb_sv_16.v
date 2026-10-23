module c_comb_sv_16 (input logic [15:0] a, b, c, output logic [15:0] y);
  always_comb y = ((a & b) | (~a & c)) ^ (b | c);
endmodule
