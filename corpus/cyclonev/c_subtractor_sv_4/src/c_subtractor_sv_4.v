module c_subtractor_sv_4 (input logic signed [3:0] a, b, output logic signed [4:0] d);
  always_comb d = a - b;
endmodule
