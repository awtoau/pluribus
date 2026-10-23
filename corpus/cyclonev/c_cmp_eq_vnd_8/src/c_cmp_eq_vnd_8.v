module c_cmp_eq_vnd_8 (a, b, y);
  input [7:0] a, b;
  output y;
  lpm_compare #(.lpm_width(8), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .aeb(y));
endmodule
