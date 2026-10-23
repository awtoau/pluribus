module c_cmp_eq_vnd_1 (a, b, y);
  input [0:0] a, b;
  output y;
  lpm_compare #(.lpm_width(1), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .aeb(y));
endmodule
