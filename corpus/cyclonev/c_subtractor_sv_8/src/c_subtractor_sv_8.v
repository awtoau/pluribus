module c_subtractor_sv_8 (input logic signed [7:0] a, b, output logic signed [8:0] d);
  always_comb d = a - b;
endmodule
