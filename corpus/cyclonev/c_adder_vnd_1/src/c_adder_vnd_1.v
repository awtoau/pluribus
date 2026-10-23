module c_adder_vnd_1 (a, b, s);
  input [0:0] a, b;
  output [1:0] s;
  wire [0:0] r;
  wire co;
  lpm_add_sub #(.lpm_width(1), .lpm_direction("ADD"), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .result(r), .cout(co));
  assign s = {co, r};
endmodule
