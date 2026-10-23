module c_subtractor_sv_16 (input logic signed [15:0] a, b, output logic signed [16:0] d);
  always_comb d = a - b;
endmodule
