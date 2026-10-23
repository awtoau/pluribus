module c_mux2_sv_1 (input logic [0:0] a, b, input logic s, output logic [0:0] y);
  always_comb if (s) y = b; else y = a;
endmodule
