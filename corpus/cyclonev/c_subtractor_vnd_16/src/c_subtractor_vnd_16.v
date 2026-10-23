module c_subtractor_vnd_16 (a, b, d);
  input [15:0] a, b;
  output [16:0] d;
  wire [15:0] r;
  wire co;
  lpm_add_sub #(.lpm_width(16), .lpm_direction("SUB"), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .result(r), .cout(co));
  assign d = {~co, r};
endmodule
