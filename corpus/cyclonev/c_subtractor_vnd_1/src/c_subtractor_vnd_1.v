module c_subtractor_vnd_1 (a, b, d);
  input [0:0] a, b;
  output [1:0] d;
  wire [0:0] r;
  wire co;
  lpm_add_sub #(.lpm_width(1), .lpm_direction("SUB"), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .result(r), .cout(co));
  assign d = {~co, r};
endmodule
