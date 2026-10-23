module c_mux2_sv_8 (input logic [7:0] a, b, input logic s, output logic [7:0] y);
  always_comb if (s) y = b; else y = a;
endmodule
