module c_subtractor_vnd_4 (a, b, d);
  input [3:0] a, b;
  output [4:0] d;
  wire [3:0] r;
  wire co;
  lpm_add_sub #(.lpm_width(4), .lpm_direction("SUB"), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .result(r), .cout(co));
  assign d = {~co, r};
endmodule
