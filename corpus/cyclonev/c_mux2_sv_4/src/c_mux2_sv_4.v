module c_mux2_sv_4 (input logic [3:0] a, b, input logic s, output logic [3:0] y);
  always_comb if (s) y = b; else y = a;
endmodule
