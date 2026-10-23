module c_cmp_eq_vnd_4 (a, b, y);
  input [3:0] a, b;
  output y;
  lpm_compare #(.lpm_width(4), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .aeb(y));
endmodule
