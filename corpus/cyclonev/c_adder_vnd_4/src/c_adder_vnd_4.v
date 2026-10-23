module c_adder_vnd_4 (a, b, s);
  input [3:0] a, b;
  output [4:0] s;
  wire [3:0] r;
  wire co;
  lpm_add_sub #(.lpm_width(4), .lpm_direction("ADD"), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .result(r), .cout(co));
  assign s = {co, r};
endmodule
