module c_subtractor_vnd_8 (a, b, d);
  input [7:0] a, b;
  output [8:0] d;
  wire [7:0] r;
  wire co;
  lpm_add_sub #(.lpm_width(8), .lpm_direction("SUB"), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .result(r), .cout(co));
  assign d = {~co, r};
endmodule
