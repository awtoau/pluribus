module c_subtractor_sv_1 (input logic signed [0:0] a, b, output logic signed [1:0] d);
  always_comb d = a - b;
endmodule
