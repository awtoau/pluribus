module c_mux2_sv_16 (input logic [15:0] a, b, input logic s, output logic [15:0] y);
  always_comb if (s) y = b; else y = a;
endmodule
