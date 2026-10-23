module c_adder_sv_16 (input logic signed [15:0] a, b, output logic signed [16:0] s);
  always_comb s = a + b;
endmodule
