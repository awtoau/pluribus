module c_adder_vnd_8 (a, b, s);
  input [7:0] a, b;
  output [8:0] s;
  wire [7:0] r;
  wire co;
  lpm_add_sub #(.lpm_width(8), .lpm_direction("ADD"), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .result(r), .cout(co));
  assign s = {co, r};
endmodule
