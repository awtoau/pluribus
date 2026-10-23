module c_comb_sv_8 (input logic [7:0] a, b, c, output logic [7:0] y);
  always_comb y = ((a & b) | (~a & c)) ^ (b | c);
endmodule
