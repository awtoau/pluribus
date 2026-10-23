module c_adder_vnd_16 (a, b, s);
  input [15:0] a, b;
  output [16:0] s;
  wire [15:0] r;
  wire co;
  lpm_add_sub #(.lpm_width(16), .lpm_direction("ADD"), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .result(r), .cout(co));
  assign s = {co, r};
endmodule
